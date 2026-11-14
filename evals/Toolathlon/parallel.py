"""并行运行已接入 personalAgent 的 Toolathlon 用例。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from evals.Toolathlon import runner
from evals.Toolathlon.pdf_cases import CASES as PDF_CASES


CASE_TARGETS = {
    **{f"time-{scenario}": ("runner", scenario)
       for scenario in ("read", "unmapped", "partial", "duplicate", "disconnect")},
    **{f"workspace-{scenario}": ("workspace_case", scenario)
       for scenario in ("approve", "reject", "disconnect")},
    "arrange-workspace": ("workspace_case", "arrange"),
    **{case: ("pdf_cases", case) for case in PDF_CASES},
    "filesystem-boundary": ("filesystem_probe", None),
    "workspace-confirmation": ("confirmation_probe", None),
}


class CaseResult(TypedDict):
    case: str
    started_at: str
    finished_at: str
    exit_code: int | None
    log: str
    report: str | None


def _case_command(case: str, args: argparse.Namespace) -> list[str]:
    module, scenario = CASE_TARGETS[case]
    command = [sys.executable, "-B", "-X", "utf8", "-m", f"evals.Toolathlon.{module}"]
    command.extend(("--output", str(args.output / case)))
    if scenario is not None:
        command.extend(("--scenario", scenario))
    if module != "filesystem_probe":
        command.extend(("--postgres-image", args.postgres_image))
    if module == "runner":
        command.extend(("--time-image", args.time_image))
    if module in {"workspace_case", "filesystem_probe", "confirmation_probe"}:
        command.extend(("--image", args.filesystem_image))
    if module in {"runner", "workspace_case", "pdf_cases"} and args.model_env is not None:
        command.extend(("--model-env", str(args.model_env)))
    if module == "pdf_cases" or case == "arrange-workspace":
        command.extend(("--upstream", str(args.upstream)))
    if module in {"workspace_case", "pdf_cases"}:
        for option, field in runner.INTERACTION_BUDGET_OPTIONS.items():
            value = getattr(args, field)
            if value is not None:
                command.extend((option, str(value)))
    return command


async def _run_case(
    case: str, command: list[str], output: Path, slots: asyncio.Semaphore,
) -> CaseResult:
    log = output / f"{case}.log"
    report = output / case / "report.json"
    async with slots:
        started_at = datetime.now(UTC).isoformat()
        with log.open("wb") as stream:
            try:
                process = await asyncio.create_subprocess_exec(
                    *command, stdin=asyncio.subprocess.DEVNULL,
                    stdout=stream, stderr=asyncio.subprocess.STDOUT,
                )
            except OSError as error:
                stream.write(f"{type(error).__name__}: {error}\n".encode("utf-8"))
                exit_code = None
            else:
                try:
                    exit_code = await process.wait()
                except asyncio.CancelledError:
                    # Console interrupts also reach the child. Let its resource cleanup finish.
                    await process.wait()
                    raise
        finished_at = datetime.now(UTC).isoformat()
        print(f"{case}: exit={exit_code}, log={log}", flush=True)
    return CaseResult(
        case=case, started_at=started_at, finished_at=finished_at, exit_code=exit_code,
        log=log.name, report=report.relative_to(output).as_posix() if report.is_file() else None,
    )


async def _run_batch(args: argparse.Namespace) -> list[CaseResult]:
    slots = asyncio.Semaphore(args.workers)
    return await asyncio.gather(*(
        _run_case(case, _case_command(case, args), args.output, slots) for case in args.cases
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="+", choices=tuple(CASE_TARGETS), help="用空格分隔的用例列表")
    parser.add_argument("--output", type=Path, required=True, help="新的批次输出目录")
    parser.add_argument("--workers", type=int, default=2, help="最多同时运行的用例数（默认 2）")
    parser.add_argument("--model-env", type=Path)
    parser.add_argument("--upstream", type=Path, default=Path("toolServer/Toolathlon"))
    parser.add_argument("--time-image", default="personal-agent-toolathlon-time:0.6.2")
    parser.add_argument("--filesystem-image", default="personal-agent-toolathlon-filesystem:2.2.0")
    parser.add_argument("--postgres-image", default="paradedb/paradedb:latest")
    runner.add_interaction_budget_arguments(parser)
    args = parser.parse_args()

    if len(set(args.cases)) != len(args.cases):
        parser.error("用例列表不能包含重复名称")
    if args.workers < 1:
        parser.error("--workers 必须是正整数")
    if args.model_env is None and any(
        CASE_TARGETS[case][0] in {"pdf_cases", "workspace_case"} for case in args.cases
    ):
        parser.error("工作区和 PDF 用例需要 --model-env")
    if args.model_env is not None and not args.model_env.is_file():
        parser.error(f"--model-env 文件不存在：{args.model_env}")
    args.output = args.output.resolve()
    try:
        args.output.mkdir(parents=True)
    except OSError as error:
        parser.error(f"无法创建新的批次输出目录：{error}")

    try:
        results = asyncio.run(_run_batch(args))
    except KeyboardInterrupt:
        return 130
    passed = all(result["exit_code"] == 0 for result in results)
    report = args.output / "report.json"
    report.write_text(
        json.dumps({"workers": args.workers, "passed": passed, "cases": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report.with_suffix(".sha256").write_text(hashlib.sha256(report.read_bytes()).hexdigest() + "\n", encoding="ascii")
    print(f"{report} [{passed}]", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
