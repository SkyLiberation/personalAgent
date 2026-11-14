"""Container entry for the official loop, with an optional MCP timeout and API usage capture."""

import json
import os
import sys
from functools import partial
from pathlib import Path

import httpx
import yaml

from scripts.decoupled import host_agent_loop
from utils.api_model import model_provider


async def capture_usage(response: httpx.Response) -> None:
    if not response.request.url.path.endswith("/chat/completions"):
        return
    await response.aread()
    data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    record = {"http_status": response.status_code, "model": data.get("model"), "usage": data.get("usage")}
    with Path("/workspace/dumps/model-usage.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")


def main() -> None:
    timeout = int(os.environ["TA_COMPARE_MCP_TIMEOUT"])
    build_config = host_agent_loop.build_gateway_runtime_mcp_config

    def configure_gateway(runtime_dir: str, gateway_server_name: str, gateway_url: str) -> str:
        result = build_config(runtime_dir, gateway_server_name, gateway_url)
        path = Path(result) / "gateway_sse.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        config["client_session_timeout_seconds"] = timeout
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        return result

    if timeout:
        host_agent_loop.build_gateway_runtime_mcp_config = configure_gateway
    model_provider.AsyncOpenAI = partial(
        model_provider.AsyncOpenAI, http_client=httpx.AsyncClient(event_hooks={"response": [capture_usage]})
    )
    sys.argv[0] = "scripts.decoupled.host_agent_loop"
    host_agent_loop.main()


if __name__ == "__main__":
    main()
