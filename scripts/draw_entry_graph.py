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


def _get_orch_graph():
    _ensure_src_on_path()

    from personal_agent.agent.service import AgentService
    from personal_agent.core.config import Settings

    settings = Settings.from_env()
    service = AgentService(settings=settings)
    return service._get_orch_graph()


def _build_mermaid(xray: int | bool = False) -> str:
    graph = _get_orch_graph()
    return graph.get_graph(xray=xray).draw_mermaid()


def _build_subgraph_mermaid(subgraph_name: str) -> str | None:
    graph = _get_orch_graph()
    for namespace, subgraph in graph.get_subgraphs(recurse=True):
        if namespace.rsplit("|", 1)[-1] == subgraph_name:
            return subgraph.get_graph().draw_mermaid()
    return None


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
        "--markdown",
        action="store_true",
        help="Wrap the Mermaid text in a Markdown ```mermaid code fence.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the Mermaid content instead of writing an asset file.",
    )
    parser.add_argument(
        "-x",
        "--xray",
        type=int,
        default=2,
        help="X-ray recursion depth for subgraph visualization (0 = top-level only, default 1).",
    )
    parser.add_argument(
        "--no-combine",
        action="store_true",
        help="Output only the X-ray graph (not combined with top-level).",
    )
    args = parser.parse_args()

    as_markdown = args.markdown or args.output.suffix.lower() == ".md"

    top_level_mermaid = _build_mermaid(xray=False)

    SUBGRAPH_NAMES = ["entry_graph", "plan_execution_graph", "react_graph"]

    if args.xray <= 0:
        content = _wrap_mermaid(top_level_mermaid, as_markdown)
    else:
        xray_mermaid = _build_mermaid(xray=args.xray)
        if args.no_combine:
            content = _wrap_mermaid(xray_mermaid, as_markdown)
        elif as_markdown:
            parts = [
                "# Entry Orchestration Graph (Top Level)\n",
                _wrap_mermaid(top_level_mermaid, as_markdown=True),
            ]
            for name in SUBGRAPH_NAMES:
                sub_mermaid = _build_subgraph_mermaid(name)
                if sub_mermaid:
                    parts.append(f"\n## Subgraph: {name}\n")
                    parts.append(_wrap_mermaid(sub_mermaid, as_markdown=True))
            parts.append(
                "\n# Entry Orchestration Graph (X-Ray depth={})\n".format(args.xray)
            )
            parts.append(_wrap_mermaid(xray_mermaid, as_markdown=True))
            content = "".join(parts)
        else:
            parts = [
                "# Entry Orchestration Graph (Top Level)\n\n",
                top_level_mermaid,
            ]
            for name in SUBGRAPH_NAMES:
                sub_mermaid = _build_subgraph_mermaid(name)
                if sub_mermaid:
                    parts.append(f"\n\n## Subgraph: {name}\n\n")
                    parts.append(sub_mermaid)
            parts.append(
                "\n\n# Entry Orchestration Graph (X-Ray depth={})\n\n".format(args.xray)
            )
            parts.append(xray_mermaid)
            parts.append("\n")
            content = "".join(parts)

    if args.stdout:
        print(content, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(args.output)
    return 0


def _wrap_mermaid(mermaid: str, as_markdown: bool) -> str:
    if as_markdown:
        return f"```mermaid\n{mermaid}\n```\n"
    return mermaid + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
