from __future__ import annotations

import argparse
import sys
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
DEFAULT_OUTPUT = ASSETS_DIR / "entry-orchestration.md"


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
        default=DEFAULT_OUTPUT,
        help=f"Output path. Defaults to {DEFAULT_OUTPUT}.",
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
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the Mermaid content instead of writing an asset file.",
    )
    args = parser.parse_args()

    mermaid = _build_mermaid(args.checkpoint_backend)
    as_markdown = args.markdown or args.output.suffix.lower() == ".md"
    content = f"```mermaid\n{mermaid}\n```\n" if as_markdown else mermaid + "\n"

    if args.stdout:
        print(content, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
