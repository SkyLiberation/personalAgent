"""局部回放共用的源采集配置与正式 Web Composition Root。"""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Literal
from urllib.parse import urlsplit, urlunsplit

from evals.provider_diagnostics.python_result_analysis_models import (
    Digest,
    GroupPlan,
    Record,
    RUN_REF,
)

if TYPE_CHECKING:
    from personal_agent.adapters.web.context import WebAppContext
    from personal_agent.kernel.config import Settings


class RootConfiguration(Record):
    """实际设置的非敏感只读投影；历史未封存的私有设置不冒称还原。"""

    data_dir: Path
    database_host: Literal["127.0.0.1"] = "127.0.0.1"
    database_port: Literal[16432] = 16432
    database_name: Literal["personal_agent_test"] = "personal_agent_test"
    model_profile_sha256: Digest
    mcp_enabled: Literal[False] = False
    mcp_servers: Literal[0] = 0
    a2a_enabled: Literal[False] = False
    background_started: Literal[False] = False
    langsmith_enabled: Literal[False] = False
    feishu_enabled: Literal[False] = False
    graphiti_group_prefix: str
    capture_provider: str
    firecrawl_endpoint_sha256: Digest
    firecrawl_credential_present: bool
    web_search_provider: str
    web_search_endpoint_sha256: Digest
    web_search_credential_present: bool
    historical_private_settings_complete: Literal[False] = False

    def comparison_identity(self) -> RootConfiguration:
        return self.model_copy(update={"data_dir": Path("OFFLINE_BRANCH/data")})


def branch_settings(plan: GroupPlan, branch: Path) -> Settings:
    """复原 collector 的显式覆盖；仅从受信进程读取凭据，不落密钥。"""
    from personal_agent.kernel.config import Settings
    from personal_agent.kernel.config_models import (
        InteractionLoopConfig,
        MCPConfig,
        ModelCapacityConfig,
    )

    settings = Settings.from_env()
    profile = json.loads(plan.source.profile.path.read_text(encoding="utf-8"))
    updates = {}
    for name in ("openai", "structured"):
        existing, archived = getattr(settings, name), profile[name]
        if (
            not existing.api_key
            or sha256((existing.base_url or "").encode()).hexdigest()
            != archived["provider_url_digest"]
        ):
            raise ValueError(f"{name}当前受信凭证／端点与源profile不符")
        model_updates = {
            key: archived[key] for key in ("model", "timeout_seconds", "max_retries")
        }
        model_updates["capacity"] = ModelCapacityConfig.model_validate(
            archived["capacity"]
        )
        if name == "structured":
            model_updates.update(
                output_transport=archived["output_transport"],
                extra_body=archived["extra_body"],
            )
        updates[name] = existing.model_copy(update=model_updates)
    database = urlsplit(settings.postgres_url or "")
    if not database.username or not database.password:
        raise ValueError("需要既有本机评测数据库凭据；不建立基础设施")
    # Same source collector binding; encoded credentials never enter reports.
    authority = database.netloc.rsplit("@", 1)[0]
    database_url = urlunsplit(
        (
            database.scheme,
            authority + "@127.0.0.1:16432",
            "/personal_agent_test",
            database.query,
            "",
        )
    )
    updates.update(
        data_dir=branch / "data",
        postgres_url=database_url,
        retrieval_experiment_config_path=plan.source.deployment.path,
        interaction_loop=InteractionLoopConfig.model_validate(profile["budget"]),
        mcp=MCPConfig(enabled=False, servers=()),
        gpt_researcher_a2a=settings.gpt_researcher_a2a.model_copy(
            update={"enabled": False}
        ),
        graphiti=settings.graphiti.model_copy(
            update={
                "group_prefix": f"{settings.graphiti.group_prefix}-offline-{plan.group_id}"
            }
        ),
        feishu=settings.feishu.model_copy(update={"enabled": False}),
        langsmith=settings.langsmith.model_copy(update={"enabled": False}),
        review_digest=settings.review_digest.model_copy(
            update={"scheduler_enabled": False}
        ),
        knowledge_gap=settings.knowledge_gap.model_copy(
            update={"scheduler_enabled": False}
        ),
        research=settings.research.model_copy(update={"scheduler_enabled": False}),
        web=settings.web.model_copy(update={"api_keys": {}, "admin_api_keys": {}}),
    )
    return Settings.model_validate(settings.model_copy(update=updates).model_dump())


def root_configuration(plan: GroupPlan, settings: Settings) -> RootConfiguration:
    return RootConfiguration(
        data_dir=settings.data_dir,
        model_profile_sha256=plan.source.profile.sha256,
        mcp_enabled=settings.mcp.enabled,
        mcp_servers=len(settings.mcp.servers),
        a2a_enabled=settings.gpt_researcher_a2a.enabled,
        langsmith_enabled=settings.langsmith.enabled,
        feishu_enabled=settings.feishu.enabled,
        graphiti_group_prefix=settings.graphiti.group_prefix,
        capture_provider=settings.url_capture_provider,
        firecrawl_endpoint_sha256=sha256(
            settings.firecrawl.base_url.encode()
        ).hexdigest(),
        firecrawl_credential_present=bool(settings.firecrawl.api_key),
        web_search_provider=settings.web_search.provider,
        web_search_endpoint_sha256=sha256(
            (settings.web_search.base_url or "").encode()
        ).hexdigest(),
        web_search_credential_present=bool(settings.web_search.api_key),
    )


def baseline_tool_port(runtime):
    """复用真实工具、policy、审计及幂等，仅移除 Python。"""
    from personal_agent.governance import ToolExecutor

    original = runtime.tool_executor
    gateway = original._gateway
    baseline = ToolExecutor(
        audit_sink=gateway.audit_sink,
        idempotency_store=gateway._idempotency,
        policy_engine=gateway._policy,
        policy_decisions=gateway._policy_decisions,
    )
    for tool in original.list_tools():
        if tool.name != "execute_python":
            baseline.register(tool)
    if len(original.list_tools()) - len(baseline.list_tools()) != 1:
        raise ValueError("正式装配必须恰有一个Python工具；baseline不能移除其他入口")
    return baseline


def build_branch_context(settings: Settings, *, baseline: bool) -> WebAppContext:
    from personal_agent.adapters.web.context import build_web_app_context

    context = build_web_app_context(settings, logging.getLogger(__name__))
    if baseline:
        runtime = context.service.runtime
        runtime._conversation_service._tool_port = baseline_tool_port(runtime)
    return context


def converse_source(service, original):
    return service.converse(
        conversation_id=original.conversation_id,
        messages=list(original.messages),
        principal=original.principal,
        source_platform="web",
        interaction_run_ref=RUN_REF,
        interaction_mode="auto",
        input_artifact_refs=original.input_artifact_refs,
    )


@contextmanager
def branch_environment(branch: Path) -> Iterator[None]:
    """现有采集输出入口也必须指向当前隔离分支。"""
    updates = {
        "PERSONAL_AGENT_E2E_TRACE_DIR": str(branch / "e2e"),
        "PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR": str(branch / "product"),
    }
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
