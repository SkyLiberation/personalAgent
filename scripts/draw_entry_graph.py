from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def _build_mermaid(checkpoint_backend: str) -> str:
    _ensure_src_on_path()

    from personal_agent.agent.service import AgentService
    from personal_agent.core.config import Settings

    settings = Settings.from_env().model_copy(
        update={
            "langgraph_checkpoint_backend": checkpoint_backend,
        }
    )
    service = AgentService(settings=settings)
    graph = service._get_orch_graph()
    return graph.get_graph().draw_mermaid()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a Mermaid diagram for the entry orchestration LangGraph."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Optional output path. When omitted, Mermaid is printed to stdout.",
    )
    parser.add_argument(
        "--checkpoint-backend",
        default="memory",
        choices=["memory", "sqlite"],
        help="Checkpoint backend used while compiling the graph. Defaults to memory.",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Wrap the Mermaid text in a Markdown ```mermaid code fence.",
    )
    args = parser.parse_args()

    mermaid = _build_mermaid(args.checkpoint_backend)
    content = f"```mermaid\n{mermaid}\n```\n" if args.markdown else mermaid + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
