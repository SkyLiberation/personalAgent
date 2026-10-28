"""Offline SDK/configuration replay of complete, sealed real model stages.

Only the external HTTP response is substituted. Two original main-adapter
stages establish behavior preservation. Graphiti/LangExtract consume the same
material for configuration-boundary checks; they are not new product E2Es.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from contextlib import contextmanager
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
from threading import Thread

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class ReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case: str
    responsibility: str
    passed: bool
    changed_fields: list[str] = Field(default_factory=list)
    wire_sha256: str | None = None


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@contextmanager
def configuration(values: dict[str, str]):
    saved = dict(os.environ)
    for key in tuple(os.environ):
        if key.startswith(("STRUCTURED_", "ROUTER_", "OPENAI_", "PERSONAL_AGENT_GRAPHITI_LLM_", "PERSONAL_AGENT_EXTRACT_")):
            del os.environ[key]
    os.environ.update(PYTHON_DOTENV_DISABLED="true", NO_PROXY="127.0.0.1,localhost")
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


class StageSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: Path
    sha256: str
    bytes: int
    keys: list[str]
    model: str
    message_count: int
    response_path: Path
    response_sha256: str


def source_values(manifest: Path) -> list[tuple[StageSource, dict]]:
    values = []
    for entry in TypeAdapter(list[StageSource]).validate_json(manifest.read_bytes()):
        path = entry.path
        payload = path.read_bytes()
        if sha256(payload).hexdigest() != entry.sha256 or sha256(entry.response_path.read_bytes()).hexdigest() != entry.response_sha256:
            raise ValueError(f"sealed source changed: {path}")
        values.append((entry, json.loads(payload)))
    return values


def main_request(wire: dict):
    from personal_agent.capabilities.contracts.model import ModelActionDefinition, StructuredModelRequest

    tools = tuple(ModelActionDefinition(
        name=item["function"]["name"], kind="tool", target_name=item["function"]["name"],
        description=item["function"]["description"], input_schema=item["function"]["parameters"],
        strict=item["function"].get("strict", True),
    ) for item in wire.get("tools", []))
    return StructuredModelRequest(
        operation="provider_configuration_replay", version="v1", messages=wire["messages"],
        output_type=BaseModel, context_projection_ref="offline:sealed-provider-stage",
        kind="tool_calling" if tools else "text", action_definitions=tools,
        action_choice=wire.get("tool_choice"), response_format=wire.get("response_format"),
        max_tokens=wire.get("max_completion_tokens", wire.get("max_tokens")),
        temperature=wire.get("temperature", 0), reasoning_effort=wire.get("reasoning_effort"),
        extra_body=wire.get("extra_body"),
    )


def worker(args) -> None:
    from personal_agent.infra.structured_model import OpenAIModelClient
    import personal_agent.infra.structured_model as implementation
    from personal_agent.kernel.config import Settings
    from personal_agent.kernel.config_models import StructuredConfig
    from openai import OpenAI

    expected = args.before_source if args.role == "before" else Path("src")
    if not Path(implementation.__file__).resolve().is_relative_to(expected.resolve()):
        raise ValueError("replay imported the wrong production source")
    output = args.output / args.role
    output.mkdir(parents=True, exist_ok=False)
    captures: list[bytes] = []
    response: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            captures.append(body)
            request = json.loads(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if request.get("stream") else "application/json")
            self.end_headers()
            if not request.get("stream"):
                self.wfile.write(json.dumps(response).encode())
                return
            base = {"id": response["id"], "object": "chat.completion.chunk", "created": response["created"], "model": response["model"]}
            choice = response["choices"][0]
            delta = dict(choice["message"])
            if delta.get("tool_calls"):
                delta["tool_calls"] = [dict(call, index=i) for i, call in enumerate(delta["tool_calls"])]
            chunks = [dict(base, choices=[{"index": 0, "delta": delta, "finish_reason": None}]),
                      dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": choice["finish_reason"]}]),
                      dict(base, choices=[], usage=response.get("usage"))]
            for chunk in chunks:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/v1"

    def policy_kwargs(base_url, provider):
        if args.role == "before":
            return {}
        from personal_agent.infra.model_providers import build_provider_policy
        return {"provider_policy": build_provider_policy(base_url=base_url, provider=provider)}

    try:
        with configuration({}):
            sources = source_values(args.manifest)
            for index, (source, wire) in enumerate(sources):
                recorded = json.loads(source.response_path.read_bytes())
                response = recorded.get("response", recorded)
                adapter = OpenAIModelClient(StructuredConfig(
                    api_key="offline-replay", base_url="https://api.minimax.cn/v1", model=wire["model"], timeout_seconds=30,
                ))
                kwargs = adapter._chat_kwargs(main_request(wire), stream=bool(wire.get("stream")))
                with OpenAI(api_key="offline-replay", base_url=endpoint, max_retries=0) as client:
                    completion = adapter._create_chat_completion(client, "offline-replay", kwargs)
                (output / f"main-{index}.http.json").write_bytes(captures[-1])
                save(output / f"main-{index}.response.json", completion.payload.model_dump(mode="json"))

        wire = sources[0][1]
        response = json.loads(sources[0][0].response_path.read_bytes())
        with configuration({"STRUCTURED_API_KEY": "offline-replay", "STRUCTURED_PROVIDER": "minimax",
                            "STRUCTURED_BASE_URL": endpoint, "STRUCTURED_MODEL": wire["model"],
                            "STRUCTURED_EXTRA_BODY": json.dumps(wire.get("extra_body", {}) | {"reasoning_effort": wire["reasoning_effort"]})}):
            settings = Settings.from_env()
            from personal_agent.memory.graphiti.llm_strategies import build_graphiti_llm_client
            graph = build_graphiti_llm_client(settings, **policy_kwargs(
                settings.graphiti.llm_base_url or settings.openai.base_url, getattr(settings.graphiti, "llm_provider", None),
            ))
            async def graph_stage():
                try:
                    await graph._create_completion_impl(
                        model=wire["model"], messages=wire["messages"], temperature=0.6,
                        max_tokens=wire["max_completion_tokens"], response_format=wire["response_format"],
                        extra_body=dict(settings.structured.extra_body), response_model_name="sealed-summary-material",
                    )
                finally:
                    await graph.client.close()

            asyncio.run(graph_stage())
            (output / "graphiti.http.json").write_bytes(captures[-1])
            from personal_agent.application.extract.langextract_client import build_language_model
            extraction = build_language_model(settings.langextract, **policy_kwargs(
                settings.langextract.base_url, getattr(settings.langextract, "provider", None),
            ))
            params = extraction._build_chat_completions_params(wire["messages"][-1]["content"], {
                "response_format": wire["response_format"], "max_output_tokens": wire["max_completion_tokens"],
            })
            extraction._client.chat.completions.create(**params)
            (output / "langextract.http.json").write_bytes(captures[-1])
            extraction._client.close()
            from personal_agent.application.artifacts.service import ArtifactService
            image = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=")
            for case, vision_model in (("image-default", ""), ("image-override", "MiniMax-M3")):
                image_settings = settings.model_copy(update={"openai": settings.openai.model_copy(update={"vision_model": vision_model})})
                prior = len(captures)
                ArtifactService(image_settings, **policy_kwargs(
                    image_settings.openai.base_url, getattr(image_settings.openai, "provider", None),
                ))._describe_image(
                    filename="provider-configuration.png", content_type="image/png", file_bytes=image,
                    question="描述图片中可见的内容。",
                )
                if len(captures) != prior + 1:
                    raise ValueError("image configuration did not reach the declared SDK boundary")
                (output / f"{case}.http.json").write_bytes(captures[-1])
        if args.role == "candidate" or args.baseline_kind == "consolidated":
            with configuration({"STRUCTURED_API_KEY": "offline-replay", "STRUCTURED_PROVIDER": "deepseek",
                                "STRUCTURED_BASE_URL": endpoint, "STRUCTURED_MODEL": "deepseek-flash",
                                "STRUCTURED_EXTRA_BODY": '{"thinking":{"type":"enabled"}}'}):
                settings = Settings.from_env()
                extraction = build_language_model(settings.langextract, **policy_kwargs(
                    settings.langextract.base_url, getattr(settings.langextract, "provider", None),
                ))
                params = extraction._build_chat_completions_params(wire["messages"][-1]["content"], {"top_p": 0.97})
                extraction._client.chat.completions.create(**params)
                (output / "deepseek-sampling.http.json").write_bytes(captures[-1])
                extraction._client.close()
            with configuration({"STRUCTURED_API_KEY": "offline-replay", "STRUCTURED_PROVIDER": "deepseek",
                                "STRUCTURED_BASE_URL": endpoint, "STRUCTURED_MODEL": "deepseek-flash",
                                "STRUCTURED_EXTRA_BODY": '{"reasoning_effort":"none"}'}):
                from dataclasses import replace
                settings = Settings.from_env()
                original = sources[1][1]
                request = replace(main_request(original), reasoning_effort=None, extra_body=None, action_choice="required")
                adapter = OpenAIModelClient(settings.structured)
                with OpenAI(api_key="offline-replay", base_url=endpoint, max_retries=0) as client:
                    adapter._create_chat_completion(client, "deepseek-none", adapter._chat_kwargs(request))
                (output / "deepseek-none.http.json").write_bytes(captures[-1])
        if args.baseline_kind == "consolidated":
            from dataclasses import replace
            recorded = json.loads(sources[1][0].response_path.read_bytes())
            response = recorded.get("response", recorded)
            with configuration({"STRUCTURED_API_KEY": "offline-replay", "STRUCTURED_PROVIDER": "mimo",
                                "STRUCTURED_BASE_URL": endpoint, "STRUCTURED_MODEL": "mimo-v2.6-flash",
                                "STRUCTURED_EXTRA_BODY": '{"thinking":{"type":"enabled"}}'}):
                settings = Settings.from_env()
                request = replace(main_request(sources[1][1]), reasoning_effort=None, extra_body=None, action_choice="required")
                adapter = OpenAIModelClient(settings.structured)
                with OpenAI(api_key="offline-replay", base_url=endpoint, max_retries=0) as client:
                    completion = adapter._create_chat_completion(client, "mimo-tools", adapter._chat_kwargs(request))
                (output / "mimo-tools.http.json").write_bytes(captures[-1])
                save(output / "mimo-tools.response.json", completion.payload.model_dump(mode="json"))
            if args.role == "candidate":
                from personal_agent.infra.model_providers import DEFAULT_PROVIDER_FACTORIES, build_provider_policy
                protected = [Path("src/personal_agent/infra/structured_model.py"), Path("src/personal_agent/kernel/model_provider.py"),
                             *sorted(Path("src/personal_agent/infra/model_providers").glob("*.py"))]
                before_hashes = {str(path): sha256(path.read_bytes()).hexdigest() for path in protected}
                extension_source = output / "offline_extension.py"
                extension_source.write_text(
                    'from personal_agent.infra.model_providers.openai_compatible import OpenAICompatiblePolicy\n\n'
                    'class OfflineExtensionPolicy(OpenAICompatiblePolicy):\n'
                    '    def configure(self, request):\n'
                    '        request.extra_body["offline_extension"] = "injected"\n'
                    '        return super().configure(request)\n', encoding="utf-8",
                )
                extension = runpy.run_path(str(extension_source))["OfflineExtensionPolicy"]
                with configuration({"STRUCTURED_API_KEY": "offline-replay", "STRUCTURED_PROVIDER": "offline_extension",
                                    "STRUCTURED_BASE_URL": endpoint, "STRUCTURED_MODEL": sources[1][1]["model"]}):
                    settings = Settings.from_env()
                    policy = build_provider_policy(base_url=settings.structured.base_url, provider=settings.structured.provider,
                                                   factories={**DEFAULT_PROVIDER_FACTORIES, "offline_extension": extension})
                    adapter = OpenAIModelClient(settings.structured, provider_policy=policy)
                    with OpenAI(api_key="offline-replay", base_url=endpoint, max_retries=0) as client:
                        adapter._create_chat_completion(client, "extension", adapter._chat_kwargs(
                            main_request(sources[1][1]), stream=bool(sources[1][1].get("stream")),
                        ))
                    (output / "extension.http.json").write_bytes(captures[-1])
                    prior = len(captures)
                    rejected = False
                    try:
                        OpenAIModelClient(settings.structured.model_copy(update={"provider": "unregistered_extension"}))
                    except ValueError:
                        rejected = True
                save(output / "extension-identity.json", {
                    "before": before_hashes, "after": {str(path): sha256(path.read_bytes()).hexdigest() for path in protected},
                    "extension_source_sha256": sha256(extension_source.read_bytes()).hexdigest(),
                    "unregistered_rejected_before_send": rejected and prior == len(captures),
                    "default_registry_unchanged": "offline_extension" not in DEFAULT_PROVIDER_FACTORIES,
                })
    finally:
        server.shutdown()
        server.server_close()


def configuration_checks(wire: dict) -> list[ReplayResult]:
    from dataclasses import replace
    from personal_agent.infra.structured_model import OpenAIModelClient
    from personal_agent.kernel.config import Settings

    request = replace(main_request(wire), extra_body=None, reasoning_effort=None)
    base = {"STRUCTURED_API_KEY": "offline-replay", "STRUCTURED_BASE_URL": "https://api.minimax.cn/v1",
            "STRUCTURED_MODEL": wire["model"], "STRUCTURED_EXTRA_BODY": '{"thinking":{"type":"adaptive"},"reasoning_effort":"medium"}'}
    results = []
    for provider, endpoint, model, extra, limit in [
        ("minimax", "https://api.minimax.cn/v1", wire["model"], base["STRUCTURED_EXTRA_BODY"], "max_completion_tokens"),
        ("mimo", "https://api.xiaomimimo.com/v1", "mimo-v2.6-flash", '{"thinking":{"type":"enabled"}}', "max_completion_tokens"),
        ("deepseek", "https://api.deepseek.com", "deepseek-flash", '{"thinking":{"type":"enabled"},"reasoning_effort":"high"}', "max_tokens"),
    ]:
        with configuration(base | {"STRUCTURED_BASE_URL": endpoint, "STRUCTURED_MODEL": model, "STRUCTURED_EXTRA_BODY": extra}):
            settings = Settings.from_env()
            kwargs = OpenAIModelClient(settings.structured)._chat_kwargs(request)
            passed = (settings.structured.provider == provider and kwargs.get(limit) == request.max_tokens
                      and kwargs["messages"] == request.messages and kwargs["tools"] == wire["tools"])
            results.append(ReplayResult(case=f"provider-{provider}", responsibility="configuration", passed=passed))

    with configuration(base | {"OPENAI_BASE_URL": "https://api.deepseek.com", "OPENAI_MODEL": "deepseek-flash",
                               "PERSONAL_AGENT_GRAPHITI_LLM_MODEL": "other-model", "PERSONAL_AGENT_EXTRACT_BASE_URL": "https://api.xiaomimimo.com/v1"}):
        s = Settings.from_env()
        passed = s.openai.extra_body == s.graphiti.llm_extra_body == s.langextract.extra_body == {}
        results.append(ReplayResult(case="independent-bindings", responsibility="configuration", passed=passed))
    with configuration(base):
        s = Settings.from_env()
        kwargs = OpenAIModelClient(s.openai, model_override="MiniMax-M3")._chat_kwargs(request)
        results.append(ReplayResult(case="actual-model-override", responsibility="configuration", passed="reasoning_effort" not in kwargs and "extra_body" not in kwargs))
    with configuration(base | {"OPENAI_EXTRA_BODY": "{}", "PERSONAL_AGENT_GRAPHITI_LLM_EXTRA_BODY": "{}", "PERSONAL_AGENT_EXTRACT_EXTRA_BODY": "{}"}):
        s = Settings.from_env()
        results.append(ReplayResult(case="explicit-empty", responsibility="configuration", passed=s.openai.extra_body == s.graphiti.llm_extra_body == s.langextract.extra_body == {}))
    with configuration(base | {"STRUCTURED_EXTRA_BODY": "{}", "ROUTER_EXTRA_BODY": base["STRUCTURED_EXTRA_BODY"]}):
        s = Settings.from_env()
        results.append(ReplayResult(case="canonical-empty", responsibility="configuration", passed=s.structured.extra_body == {}))
    with configuration(base | {"STRUCTURED_EXTRA_BODY": '{"thinking":{"type":"adaptive"},"reasoning_effort":"max"}'}):
        from personal_agent.application.conversation.models import StoredModelRequest
        s = Settings.from_env()
        restored = StoredModelRequest.from_request(request).restore(BaseModel)
        kwargs = OpenAIModelClient(s.structured)._chat_kwargs(restored)
        results.append(ReplayResult(case="configured-max-journal", responsibility="configuration", passed=kwargs.get("reasoning_effort") == "max"))
    for name, overrides in [
        ("invalid-json", {"STRUCTURED_EXTRA_BODY": "{"}),
        ("invalid-object", {"STRUCTURED_EXTRA_BODY": "[]"}),
        ("provider-conflict", {"STRUCTURED_PROVIDER": "deepseek"}),
        ("unsupported-thinking", {"STRUCTURED_EXTRA_BODY": '{"thinking":{"type":"disabled"}}'}),
        ("unsupported-effort", {"STRUCTURED_EXTRA_BODY": '{"reasoning_effort":"none"}'}),
        ("managed-override", {"STRUCTURED_EXTRA_BODY": '{"messages":[]}'}),
        ("conflicting-thinking-effort", {"STRUCTURED_PROVIDER": "deepseek", "STRUCTURED_BASE_URL": "https://api.deepseek.com",
                                        "STRUCTURED_MODEL": "deepseek-flash", "STRUCTURED_EXTRA_BODY": '{"thinking":{"type":"enabled"},"reasoning_effort":"none"}'}),
    ]:
        rejected = False
        with configuration(base | overrides):
            try:
                s = Settings.from_env()
                OpenAIModelClient(s.structured)._chat_kwargs(request)
            except ValueError:
                rejected = True
        results.append(ReplayResult(case=name, responsibility="configuration-refusal", passed=rejected))
    return results


def run(args) -> None:
    args.output.mkdir(parents=True, exist_ok=False)
    initial_identity = {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "before_source_sha256": {str(path.relative_to(args.before_source)): sha256(path.read_bytes()).hexdigest()
                                 for path in sorted(args.before_source.rglob("*.py"))},
        "candidate_source_sha256": {str(path): sha256(path.read_bytes()).hexdigest() for path in sorted(Path("src").rglob("*.py"))},
        "replay_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    save(args.output / "code-identity.json", initial_identity)
    (args.output / "candidate.patch").write_bytes(subprocess.check_output(["git", "diff", "--binary", "HEAD"]))
    (args.output / "provider-source.py").write_bytes(Path("src/personal_agent/kernel/model_provider.py").read_bytes())
    if args.baseline_kind == "consolidated":
        shutil.copytree("src/personal_agent/infra/model_providers", args.output / "provider-sources", ignore=shutil.ignore_patterns("__pycache__"))
    for role in ("before", "candidate"):
        env = dict(os.environ, PYTHONPATH=str(args.before_source.resolve()) if role == "before" else str(Path("src").resolve()))
        command = [sys.executable, "-m", "evals.provider_diagnostics.model_provider_configuration", "--role", role,
                   "--before-source", str(args.before_source), "--manifest", str(args.manifest), "--output", str(args.output),
                   "--baseline-kind", args.baseline_kind]
        completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
        (args.output / f"{role}.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(f"{role} replay failed; see {args.output / (role + '.log')}")
    results = []
    for case in ("main-0", "main-1", "graphiti", "langextract"):
        before = json.loads((args.output / "before" / f"{case}.http.json").read_bytes())
        candidate_bytes = (args.output / "candidate" / f"{case}.http.json").read_bytes()
        candidate = json.loads(candidate_bytes)
        changed = sorted(key for key in before.keys() | candidate.keys() if before.get(key) != candidate.get(key))
        if args.baseline_kind == "legacy" and case in {"graphiti", "langextract"}:
            before["max_completion_tokens"] = before.pop("max_tokens")
            before.pop("temperature", None)  # MiniMax ignores this field; numeric budget is preserved.
        passed = before == candidate
        if case.startswith("main"):
            passed = (passed and (args.output / "before" / f"{case}.http.json").read_bytes() == candidate_bytes
                      and (args.output / "before" / f"{case}.response.json").read_bytes() == (args.output / "candidate" / f"{case}.response.json").read_bytes())
        results.append(ReplayResult(case=case, responsibility="real-stage" if case.startswith("main") else "adapter-configuration",
                                    passed=passed, changed_fields=changed, wire_sha256=sha256(candidate_bytes).hexdigest()))
    results.extend(configuration_checks(source_values(args.manifest)[1][1]))
    for case, model in (("image-default", "MiniMax-M3.1-Flash"), ("image-override", "MiniMax-M3")):
        before = json.loads((args.output / "before" / f"{case}.http.json").read_bytes())
        candidate = json.loads((args.output / "candidate" / f"{case}.http.json").read_bytes())
        limit_field = "max_tokens" if args.baseline_kind == "legacy" else "max_completion_tokens"
        passed = (candidate["model"] == model and candidate.get("max_completion_tokens") == before[limit_field] == 900
                  and candidate["messages"] == before["messages"])
        if args.baseline_kind == "consolidated":
            passed = passed and before == candidate
        if case == "image-override":
            passed = passed and "thinking" not in candidate and "reasoning_effort" not in candidate
        else:
            passed = passed and candidate.get("reasoning_effort") == before["reasoning_effort"]
        results.append(ReplayResult(case=case, responsibility="adapter-configuration", passed=passed))
    sampling = json.loads((args.output / "candidate" / "deepseek-sampling.http.json").read_bytes())
    results.append(ReplayResult(case="deepseek-sampling", responsibility="adapter-configuration", passed=sampling.get("top_p") == 0.97))
    disabled = json.loads((args.output / "candidate" / "deepseek-none.http.json").read_bytes())
    results.append(ReplayResult(case="deepseek-none", responsibility="adapter-configuration",
                                passed=disabled.get("reasoning_effort") == "none" and disabled.get("temperature") == 0 and disabled.get("tool_choice") == "required"))
    if args.baseline_kind == "consolidated":
        for case in ("deepseek-sampling", "deepseek-none"):
            if (args.output / "before" / f"{case}.http.json").read_bytes() != (args.output / "candidate" / f"{case}.http.json").read_bytes():
                raise ValueError(f"consolidated baseline drift: {case}")
        mimo = json.loads((args.output / "candidate/mimo-tools.http.json").read_bytes())
        mimo_equal = all((args.output / "before" / f"mimo-tools.{suffix}.json").read_bytes() ==
                         (args.output / "candidate" / f"mimo-tools.{suffix}.json").read_bytes() for suffix in ("http", "response"))
        results.append(ReplayResult(case="mimo-tools", responsibility="adapter-configuration", passed=mimo_equal and mimo.get("stream") is True
                                    and mimo.get("tool_choice") == "auto" and mimo.get("stream_options") == {"include_usage": True}))
        extension = json.loads((args.output / "candidate/extension.http.json").read_bytes())
        original = json.loads((args.output / "candidate/main-1.http.json").read_bytes())
        identity = json.loads((args.output / "candidate/extension-identity.json").read_bytes())
        marker = extension.pop("offline_extension", None)
        results.append(ReplayResult(case="independent-extension", responsibility="engineering-extensibility", passed=marker == "injected"
                                    and extension == original and identity["before"] == identity["after"] and identity["default_registry_unchanged"]))
        results.append(ReplayResult(case="unregistered-provider", responsibility="engineering-extensibility",
                                    passed=identity["unregistered_rejected_before_send"]))
    final_identity = {
        "candidate_source_sha256": {str(path): sha256(path.read_bytes()).hexdigest() for path in sorted(Path("src").rglob("*.py"))},
        "replay_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    save(args.output / "final-code-identity.json", final_identity)
    if any(initial_identity[key] != value for key, value in final_identity.items()):
        raise ValueError("production or replay source changed during validation")
    save(args.output / "report.json", {"baseline": "5e0963e" if args.baseline_kind == "legacy" else str(args.before_source),
                                       "sources": json.loads(args.manifest.read_bytes()),
                                       "paid_requests": 0, "cases": [r.model_dump() for r in results]})
    print(json.dumps({"passed": sum(r.passed for r in results), "total": len(results), "report": str(args.output / "report.json")}, ensure_ascii=False))
    if not all(r.passed for r in results):
        raise ValueError("provider configuration replay failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role", choices=("before", "candidate"))
    parser.add_argument("--baseline-kind", choices=("legacy", "consolidated"), default="legacy")
    args = parser.parse_args()
    worker(args) if args.role else run(args)
