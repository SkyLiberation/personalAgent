"""Shared live HTTP fixtures and external capability profile checks."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from typing import IO, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import pytest

from evals.e2e_quality.trace_archive import TraceArchive
from personal_agent.kernel.config import Settings, StructuredConfig
from tests.conftest import POSTGRES_URL


pytestmark = pytest.mark.integration


def _live_e2e_required() -> bool:
    return os.getenv("PERSONAL_AGENT_REQUIRE_LIVE_E2E", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _require_live_dependencies() -> Settings:
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=0.5):
            pass
    except OSError:
        message = "release E2E requires Postgres on 127.0.0.1:5432"
        if _live_e2e_required():
            pytest.fail(message)
        pytest.skip(message)

    settings = _release_profile_settings(Settings.from_env())
    if not (
        settings.structured.api_key
        and settings.structured.base_url
        and settings.structured.model
    ):
        message = "release E2E requires a real STRUCTURED_*, ROUTER_* or OPENAI_* model"
        if _live_e2e_required():
            pytest.fail(message)
        pytest.skip(message)
    return settings


def _release_profile_settings(settings: Settings) -> Settings:
    """Freeze one real model deployment for the whole release test process."""
    profile = os.getenv("PERSONAL_AGENT_E2E_MODEL_PROFILE", "configured").strip().lower()
    timeout_seconds = float(
        os.getenv("PERSONAL_AGENT_E2E_MODEL_TIMEOUT_SECONDS", "120")
    )
    if profile == "configured":
        source = settings.structured
    elif profile == "chat":
        source = settings.openai
    else:
        pytest.fail(
            "PERSONAL_AGENT_E2E_MODEL_PROFILE must be 'chat' or 'configured'"
        )
    return settings.model_copy(update={
        "openai": settings.openai.model_copy(update={
            "api_key": source.api_key,
            "base_url": source.base_url,
            "model": source.model,
            "small_model": source.model,
            "timeout_seconds": timeout_seconds,
            "max_retries": source.max_retries,
        }),
        "structured": StructuredConfig(
            api_key=source.api_key,
            base_url=source.base_url,
            model=source.model,
            timeout_seconds=timeout_seconds,
            max_retries=source.max_retries,
            extra_body=(source.extra_body if isinstance(source, StructuredConfig) else {}),
        ),
    })


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _set_optional(env: dict[str, str], name: str, value: object | None) -> None:
    if value is not None and str(value):
        env[name] = str(value)
    else:
        env.pop(name, None)


def _child_environment(settings: Settings, temp_dir: Path) -> dict[str, str]:
    """Materialize the exact real configuration for the isolated child process."""
    env = os.environ.copy()
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env["PERSONAL_AGENT_DATA_DIR"] = str(temp_dir / "server-data")
    env["PERSONAL_AGENT_POSTGRES_URL"] = POSTGRES_URL
    env["PERSONAL_AGENT_GRAPHITI_GROUP_PREFIX"] = (
        f"{settings.graphiti.group_prefix}-release-e2e-{uuid4().hex}"
    )
    env["PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_ENABLED"] = "false"
    env["PERSONAL_AGENT_KNOWLEDGE_GAP_SCHEDULER_ENABLED"] = "false"
    env["PERSONAL_AGENT_RESEARCH_SCHEDULER_ENABLED"] = "false"
    env["PERSONAL_AGENT_LANGSMITH_ENABLED"] = "false"
    env["PERSONAL_AGENT_FEISHU_ENABLED"] = "false"
    env.pop("PERSONAL_AGENT_API_KEYS", None)
    env.pop("PERSONAL_AGENT_ADMIN_API_KEYS", None)
    env.pop("FEISHU_APP_ID", None)
    env.pop("FEISHU_APP_SECRET", None)

    _set_optional(env, "STRUCTURED_API_KEY", settings.structured.api_key)
    _set_optional(env, "STRUCTURED_BASE_URL", settings.structured.base_url)
    _set_optional(env, "STRUCTURED_MODEL", settings.structured.model)
    _set_optional(
        env,
        "PERSONAL_AGENT_STRUCTURED_TIMEOUT_SECONDS",
        settings.structured.timeout_seconds,
    )
    _set_optional(
        env,
        "PERSONAL_AGENT_STRUCTURED_MAX_RETRIES",
        settings.structured.max_retries,
    )
    _set_optional(env, "OPENAI_API_KEY", settings.openai.api_key)
    _set_optional(env, "OPENAI_BASE_URL", settings.openai.base_url)
    _set_optional(env, "OPENAI_MODEL", settings.openai.model)
    _set_optional(env, "OPENAI_SMALL_MODEL", settings.openai.small_model)
    _set_optional(
        env,
        "PERSONAL_AGENT_OPENAI_TIMEOUT_SECONDS",
        settings.openai.timeout_seconds,
    )
    _set_optional(
        env,
        "PERSONAL_AGENT_OPENAI_MAX_RETRIES",
        settings.openai.max_retries,
    )
    _set_optional(env, "PERSONAL_AGENT_GRAPHITI_URI", settings.graphiti.uri)
    _set_optional(env, "PERSONAL_AGENT_GRAPHITI_USER", settings.graphiti.user)
    _set_optional(env, "PERSONAL_AGENT_GRAPHITI_PASSWORD", settings.graphiti.password)

    repository = Path(__file__).resolve().parents[2]
    python_paths = [str(repository), str(repository / "src")]
    existing = env.get("PYTHONPATH")
    if existing:
        python_paths.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    return env


@dataclass(slots=True)
class LiveWebProcess:
    base_url: str
    log_path: Path
    settings: Settings
    cwd: Path
    child_env: dict[str, str]
    port: int
    process: subprocess.Popen | None = None
    log_handle: IO[str] | None = None

    def start(self) -> None:
        assert self.process is None
        self.log_handle = self.log_path.open("a", encoding="utf-8")
        self.process = subprocess.Popen(
            (
                sys.executable,
                "-m",
                "uvicorn",
                "personal_agent.adapters.web.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "info",
            ),
            cwd=self.cwd,
            env=self.child_env,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                pytest.fail(
                    f"Web process exited during startup ({self.process.returncode}).\n"
                    f"{_server_log(self.log_path)}"
                )
            try:
                with urlopen(f"{self.base_url}/api/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except (HTTPError, URLError, TimeoutError):
                time.sleep(0.1)
        pytest.fail(f"Web process did not become healthy.\n{_server_log(self.log_path)}")

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.process = None
        if self.log_handle is not None:
            self.log_handle.close()
            self.log_handle = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def crash_and_restart(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)
        self.process = None
        if self.log_handle is not None:
            self.log_handle.close()
            self.log_handle = None
        self.start()


def _server_log(log_path: Path) -> str:
    try:
        return log_path.read_text(encoding="utf-8", errors="replace")[-20_000:]
    except OSError:
        return "<server log unavailable>"


def _new_live_web_process(
    temp_dir: Path,
    settings: Settings,
    *,
    child_env_overrides: dict[str, str] | None = None,
) -> LiveWebProcess:
    port = _free_port()
    child_env = _child_environment(settings, temp_dir)
    child_env.update(child_env_overrides or {})
    return LiveWebProcess(
        base_url=f"http://127.0.0.1:{port}",
        log_path=temp_dir / "web-process.log",
        settings=settings,
        cwd=temp_dir,
        child_env=child_env,
        port=port,
    )


def _yield_started_server(server: LiveWebProcess) -> Iterator[LiveWebProcess]:
    try:
        server.start()
        yield server
    finally:
        server.stop()


@pytest.fixture(scope="module")
def live_web_process(server_temp_dir: Path) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    yield from _yield_started_server(_new_live_web_process(
        server_temp_dir,
        settings,
        child_env_overrides={
            "PERSONAL_AGENT_MCP_SERVERS": '{"enabled":false}',
            "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
            "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
        },
    ))


@pytest.fixture(scope="module")
def live_github_mcp_web_process(server_temp_dir: Path) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    server = _new_github_mcp_web_process(server_temp_dir / "github-mcp", settings)
    yield from _yield_started_server(server)


def _new_github_mcp_web_process(
    profile_temp_dir: Path,
    settings: Settings,
) -> LiveWebProcess:
    if not shutil.which("docker"):
        message = "E16 profile requires Docker and the official GitHub MCP server"
        if _live_e2e_required():
            pytest.fail(message)
        pytest.skip(message)
    if not os.getenv("GITHUB_PAT", "").strip():
        message = "E16 profile requires GITHUB_PAT"
        if _live_e2e_required():
            pytest.fail(message)
        pytest.skip(message)
    profile_temp_dir.mkdir(parents=True)
    return _new_live_web_process(
        profile_temp_dir,
        settings,
        child_env_overrides={
            "PERSONAL_AGENT_MCP_SERVERS": '{"enabled":false}',
            "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "true",
            "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
            "PERSONAL_AGENT_GITHUB_MCP_READ_ONLY": "1",
            "PERSONAL_AGENT_GITHUB_MCP_TIMEOUT_SECONDS": "30",
        },
    )


@pytest.fixture(scope="module")
def live_notion_mcp_web_process(server_temp_dir: Path) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    server = _new_notion_mcp_web_process(server_temp_dir / "notion-mcp", settings)
    yield from _yield_started_server(server)


def _new_notion_mcp_web_process(
    profile_temp_dir: Path,
    settings: Settings,
) -> LiveWebProcess:
    _notion_e2e_resource()
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        message = "E18 profile requires npx and the official Notion MCP server"
        if _live_e2e_required():
            pytest.fail(message)
        pytest.skip(message)
    if not os.getenv("NOTION_TOKEN", "").strip():
        message = "E18 profile requires NOTION_TOKEN"
        if _live_e2e_required():
            pytest.fail(message)
        pytest.skip(message)
    profile_temp_dir.mkdir(parents=True)
    return _new_live_web_process(
        profile_temp_dir,
        settings,
        child_env_overrides={
            "PERSONAL_AGENT_MCP_SERVERS": '{"enabled":false}',
            "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
            "PERSONAL_AGENT_NOTION_MCP_ENABLED": "true",
            "PERSONAL_AGENT_NOTION_MCP_COMMAND": npx,
            "PERSONAL_AGENT_NOTION_MCP_TIMEOUT_SECONDS": "30",
        },
    )


def _notion_e2e_resource() -> tuple[str, str]:
    page_id = os.getenv("PERSONAL_AGENT_E2E_NOTION_PAGE_ID", "").strip()
    expected = os.getenv("PERSONAL_AGENT_E2E_NOTION_EXPECTED_TEXT", "").strip()
    try:
        UUID(page_id)
    except ValueError:
        page_id = ""
    if page_id and expected:
        return page_id, expected
    message = (
        "E18 requires a UUID PERSONAL_AGENT_E2E_NOTION_PAGE_ID and non-empty "
        "PERSONAL_AGENT_E2E_NOTION_EXPECTED_TEXT for an explicit test page"
    )
    if _live_e2e_required():
        pytest.fail(message)
    pytest.skip(message)


@pytest.fixture(scope="module")
def live_a2a_web_process(server_temp_dir: Path) -> Iterator[LiveWebProcess]:
    settings = _require_live_dependencies()
    endpoint = os.getenv("PERSONAL_AGENT_E2E_A2A_ENDPOINT", "http://127.0.0.1:8001/a2a")
    card_url = os.getenv(
        "PERSONAL_AGENT_E2E_A2A_AGENT_CARD_URL",
        "http://127.0.0.1:8001/.well-known/agent-card.json",
    )
    try:
        with urlopen(card_url, timeout=3) as response:
            if response.status != 200:
                raise RuntimeError(f"agent card returned HTTP {response.status}")
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
        message = f"E17 profile requires a live GPT Researcher A2A provider: {exc}"
        if _live_e2e_required():
            pytest.fail(message)
        pytest.skip(message)
    server = _new_live_web_process(
        server_temp_dir,
        settings,
        child_env_overrides={
            "PERSONAL_AGENT_MCP_SERVERS": '{"enabled":false}',
            "PERSONAL_AGENT_GITHUB_MCP_ENABLED": "false",
            "PERSONAL_AGENT_NOTION_MCP_ENABLED": "false",
            "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED": "true",
            "PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENDPOINT": endpoint,
            "PERSONAL_AGENT_GPT_RESEARCHER_A2A_AGENT_CARD_URL": card_url,
            "PERSONAL_AGENT_GPT_RESEARCHER_A2A_TIMEOUT_SECONDS": "120",
            "PERSONAL_AGENT_GPT_RESEARCHER_A2A_MAX_SEARCH_RESULTS": "1",
        },
    )
    yield from _yield_started_server(server)


def _get_json(url: str) -> object:
    with urlopen(url, timeout=30) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=300) as response:
            assert response.status == 200
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        exc.msg = f"{exc.msg}; response_body={body[:1000]}"
        raise


def _post_text_attachment(
    url: str,
    *,
    filename: str,
    content: str,
    fields: dict[str, str],
) -> dict[str, object]:
    boundary = f"release-e2e-{uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend((
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ))
    chunks.extend((
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n",
        content.encode("utf-8"),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ))
    request = Request(
        url,
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(request, timeout=300) as response:
        assert response.status == 200
        return json.loads(response.read().decode("utf-8"))


def test_e16_http_process_reads_github_through_real_mcp_gateway(
    live_github_mcp_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    owner = os.getenv("PERSONAL_AGENT_E2E_GITHUB_OWNER", "github")
    repository = os.getenv("PERSONAL_AGENT_E2E_GITHUB_REPO", "github-mcp-server")
    path = os.getenv("PERSONAL_AGENT_E2E_GITHUB_PATH", "README.md")
    expected = os.getenv("PERSONAL_AGENT_E2E_GITHUB_EXPECTED_TEXT", "GitHub MCP Server")
    result = _post_json(
        f"{live_github_mcp_web_process.base_url}/api/conversation/turn",
        {
            "conversation_id": f"release-e16-github-{uuid4().hex}",
            "messages": [{"role": "user", "content": (
                "必须只调用 github.get_file_contents，使用参数 "
                f"owner={owner!r}, repo={repository!r}, path={path!r}。"
                f"根据真实 ToolResult 找到准确文本 {expected!r}，并把该文本逐字抄写为最终答案；"
                "不要只回答包含或不包含，禁止调用写工具。"
            )}],
        },
    )
    trace = _get_json(
        f"{live_github_mcp_web_process.base_url}/api/conversation/runs/{result['interaction_run_ref']}"
    )
    mcp_results = [
        item for item in trace["inputs"]
        if item["kind"] == "tool_result"
        and item["capability_id"] == "github.get_file_contents"
    ]
    tool_results = [item for item in trace["inputs"] if item["kind"] == "tool_result"]
    successful_results = [item for item in mcp_results if item["status"] == "succeeded"]
    serialized_results = json.dumps(mcp_results, ensure_ascii=False, default=str)
    assert result["disposition"] == "answer"
    assert tool_results == mcp_results
    assert len(successful_results) == 1
    assert all(
        '"provider": "mcp"' in json.dumps(item, ensure_ascii=False, default=str)
        and '"server_id": "github"' in json.dumps(item, ensure_ascii=False, default=str)
        for item in mcp_results
    )
    assert expected in serialized_results
    assert expected in str(result["message"]["content"])
    assert not any(key in result for key in ("task", "plan", "command", "completion_report"))
    trace_archive.write_trace(
        nodeid=request.node.nodeid,
        case_id="E16.release_http_real_github_mcp",
        trace={
            "result": result,
            "interaction_trace": trace,
            "resource": {"owner": owner, "repository": repository, "path": path},
        },
    )


def test_e18_http_process_reads_notion_through_real_mcp_gateway(
    live_notion_mcp_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    page_id, expected = _notion_e2e_resource()
    result = _post_json(
        f"{live_notion_mcp_web_process.base_url}/api/conversation/turn",
        {
            "conversation_id": f"release-e18-notion-{uuid4().hex}",
            "messages": [{"role": "user", "content": (
                "必须只调用 notion.retrieve_page_markdown，使用参数 "
                f"page_id={page_id!r}。根据真实 ToolResult 找到准确文本 {expected!r}，"
                "并把该文本逐字抄写为最终答案；不要只回答包含或不包含，禁止调用任何写工具。"
            )}],
        },
    )
    trace = _get_json(
        f"{live_notion_mcp_web_process.base_url}/api/conversation/runs/{result['interaction_run_ref']}"
    )
    mcp_results = [
        item for item in trace["inputs"]
        if item["kind"] == "tool_result"
        and item["capability_id"] == "notion.retrieve_page_markdown"
    ]
    tool_results = [item for item in trace["inputs"] if item["kind"] == "tool_result"]
    successful_results = [item for item in mcp_results if item["status"] == "succeeded"]
    serialized_results = json.dumps(mcp_results, ensure_ascii=False, default=str)
    assert result["disposition"] == "answer"
    assert tool_results == mcp_results
    assert len(successful_results) == 1
    assert all(
        '"provider": "mcp"' in json.dumps(item, ensure_ascii=False, default=str)
        and '"server_id": "notion"' in json.dumps(item, ensure_ascii=False, default=str)
        for item in mcp_results
    )
    assert expected in serialized_results
    assert expected in str(result["message"]["content"])
    assert not any(key in result for key in ("task", "plan", "command", "completion_report"))
    trace_archive.write_trace(
        nodeid=request.node.nodeid,
        case_id="E18.release_http_real_notion_mcp",
        trace={"result": result, "interaction_trace": trace, "page_id": page_id},
    )


def test_e19_http_process_mcp_capability_unavailable_fails_closed(
    live_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    result = _post_json(
        f"{live_web_process.base_url}/api/conversation/turn",
        {
            "conversation_id": f"release-e19-mcp-unavailable-{uuid4().hex}",
            "messages": [{"role": "user", "content": (
                "必须使用 GitHub 或 Notion MCP 读取外部资料。若当前能力列表没有这两个 "
                "Connector，返回 disposition=limitation；禁止调用其他工具或用常识替代。"
            )}],
        },
    )
    trace = _get_json(
        f"{live_web_process.base_url}/api/conversation/runs/{result['interaction_run_ref']}"
    )
    assert result["disposition"] == "limitation"
    assert trace["usage"]["tool_calls"] == 0
    assert not any(item["kind"] == "tool_result" for item in trace["inputs"])
    assert not any(key in result for key in ("task", "plan", "command", "completion_report"))
    trace_archive.write_trace(
        nodeid=request.node.nodeid,
        case_id="E19.release_http_mcp_capability_unavailable",
        trace={"result": result, "interaction_trace": trace},
    )


def test_e17_http_process_delegates_to_real_a2a_and_verifies_parent_result(
    live_a2a_web_process: LiveWebProcess,
    trace_archive: TraceArchive,
    request: pytest.FixtureRequest,
) -> None:
    result = _post_json(
        f"{live_a2a_web_process.base_url}/api/conversation/turn",
        {
                "conversation_id": f"release-e17-a2a-{uuid4().hex}",
                "messages": [{"role": "user", "content": (
                    "请委托 gpt_researcher 研究 Agent2Agent（A2A）协议的目的，优先使用 "
                    "a2a-protocol.org 的官方协议文档，并基于返回的 "
                    "AgentArtifact 给出一句中文总结。唯一用户结果是总结，研究报告只是中间证据；"
                    "远端 completed 不能自动完成你的父级回答。"
                )}],
        },
    )
    trace = _get_json(
        f"{live_a2a_web_process.base_url}/api/conversation/runs/{result['interaction_run_ref']}"
    )
    agent_artifacts = [item for item in trace["inputs"] if item["kind"] == "agent_artifact"]
    assert result["disposition"] == "answer"
    assert len(agent_artifacts) == 1
    assert agent_artifacts[0]["capability_id"] == "gpt_researcher"
    assert agent_artifacts[0]["status"] == "succeeded"
    artifact = agent_artifacts[0]["payload"]["artifacts"][0]
    excerpt = artifact["content_excerpt"]
    assert artifact["content_length"] > 200
    assert "data:" not in excerpt
    assert "[DONE]" not in excerpt
    assert "Cancellation requested" not in excerpt
    assert agent_artifacts[0]["payload"]["artifact_refs"]
    assert trace["final_message"]["message"] == result["message"]["content"]
    assert trace["usage"]["agent_calls"] == 1
    assert not any(key in result for key in ("task", "plan", "command", "completion_report"))
    trace_archive.write_trace(
        nodeid=request.node.nodeid,
        case_id="E17.release_http_real_a2a_delegation",
        trace={"result": result, "interaction_trace": trace, "agent_artifact": agent_artifacts[0]},
    )
