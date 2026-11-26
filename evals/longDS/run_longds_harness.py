"""Run sealed LongDS material through the official SDK and native tools."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values

from evals.deepseek_runtime import VERSION, native_runtime, write_profile
from evals.run_deepseek_harness import SDK_SOURCE, sha256
from . import harness_preflight
from .longds_materials import LongDSPreparation, json_bytes, seal, verify_preparation
from .skill_session import SKILL_NAME, SKILL_REVISION, SKILL_ROOT, first_question


IMAGE = "personal-agent-dsh-longds:local"
PROVIDER = "longds-minimax"
MODEL_OUTPUT_LIMIT = 32_768
TASK_TOKEN_LIMIT = 60_000_000
TURN_TIMEOUT_SECONDS = 3600
MODULE_DIR = Path(__file__).resolve().parent


def write_record(path: Path, record: object) -> None:
    pending = path.with_suffix(".pending")
    pending.write_bytes(json_bytes(record))
    pending.replace(path)


def prepare_workspace(run: Path, prepared: LongDSPreparation, materials: Path) -> Path:
    data = run / "data"
    data.mkdir()
    for item in prepared.inputs:
        target = data / item.filename
        shutil.copyfile(materials / "data" / item.filename, target)
        if sha256(target) != item.sha256:
            raise ValueError("LongDS input changed when copied")
    return data


def run_task(
    materials: Path,
    run: Path,
    endpoint: tuple[str, str, str],
    image: str,
    *,
    probe: harness_preflight.FilesystemPreflight | None = None,
    persistent_bash: bool = False,
    memory_mb: int | None = None,
) -> int:
    base_url, model, key = endpoint
    memory_mb = (1024 if persistent_bash else 512) if memory_mb is None else memory_mb
    if memory_mb <= 0:
        raise ValueError("Memory limit must be positive")
    prepared = verify_preparation(materials)
    run.mkdir(parents=True, exist_ok=False)
    data = prepare_workspace(run, prepared, materials)
    profile = write_profile(
        run / "profile", workspace="/workspace", provider=PROVIDER, model=model, base_url=base_url,
        persona="You are a helpful assistant. Task files are read-only in /workspace. "
        "Bash and the file tools share /workspace and the writable /tmp. "
        "Analyze the supplied data and answer the user.",
        window=1_000_000, output_limit=MODEL_OUTPUT_LIMIT, step_limit=40,
        skill=persistent_bash, persistent_bash=persistent_bash,
    )
    mounts = (f"type=bind,source={data},target=/workspace,readonly",)
    if persistent_bash:
        mounts += (f"type=bind,source={SKILL_ROOT},target=/dsh-skills,readonly",)
    report = {
        "task": prepared.task, "dataset_revision": prepared.dataset_revision,
        "harness_version": VERSION, "profile_sha256": sha256(profile),
        "runner_sha256": sha256(Path(__file__)),
        "model": model, "provider_host": urlsplit(base_url).hostname, "language": prepared.language,
        "image": image, "session_id": f"longds-{uuid4().hex}", "started_at": datetime.now(UTC).isoformat(),
        "requested_turns": 0, "answered_turns": 0, "planned_turns": len(prepared.turns),
        "run_kind": "tool_preflight" if probe is not None else "longds_capture",
        "known_tokens": 0, "unknown_usage_steps": 0, "stop_reason": "preflight",
        "persistent_bash": persistent_bash, "goal_mode": "disabled",
        "memory_mb": memory_mb,
        "skill_revision": SKILL_REVISION if persistent_bash else None,
        "bundled_skills": [SKILL_NAME] if persistent_bash else [],
    }
    started = monotonic()
    try:
        with native_runtime(
            run, profile, SDK_SOURCE, image=image, workspace="/workspace",
            mounts=mounts,
            provider=PROVIDER, model=model, provider_key=key, output_limit=MODEL_OUTPUT_LIMIT,
            timeout=90 if probe is not None else TURN_TIMEOUT_SECONDS, memory_mb=memory_mb,
        ) as (runtime, _):
            session = runtime.start_session(report["session_id"])
            if probe is not None:
                probe.run(session, run / "tool-preflight.json")
                report["stop_reason"] = "preflight_ok"
            for turn in (() if probe is not None else prepared.turns):
                if (run / "stop-after-turn").exists() or report["known_tokens"] >= TASK_TOKEN_LIMIT:
                    report["stop_reason"] = ("task_token_limit" if report["known_tokens"] >= TASK_TOKEN_LIMIT
                                             else "operator_stop_after_turn")
                    break
                turn_started = monotonic()
                prefix = run / f"turn-{turn.turn_id:02}"
                prompt = turn.user_message(language=prepared.language)
                if persistent_bash and turn.turn_id == 1:
                    prompt = first_question(
                        prompt, data_directory="/workspace",
                        script_location=f"/dsh-skills/{SKILL_NAME}/scripts/pysession.py",
                        language=prepared.language,
                    )
                prefix.with_suffix(".prompt.txt").write_bytes(prompt.encode("utf-8"))
                report["requested_turns"] += 1
                write_record(run / "progress.json", report)
                result = session.run(prompt)
                usage = [event["data"]["usage"] for event in result.events
                         if event.get("type") == "assistant/message" and event.get("data", {}).get("usage")]
                counts = Counter(event["type"] for event in result.events)
                tokens = sum(int(item.get("totalTokens") or sum(item.get(field, 0) for field in (
                    "inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens",
                ))) for item in usage)
                report["known_tokens"] += tokens
                report["unknown_usage_steps"] += max(0, counts["step/start"] - len(usage))
                delivered = result.finish_reason == "completed" and bool(result.final_response.strip())
                write_record(prefix.with_suffix(".json"), {
                    "turn_id": turn.turn_id, "session_id": result.session_id,
                    "finish_reason": result.finish_reason, "answer": result.final_response, "delivered": delivered,
                    "wall_seconds": round(monotonic() - turn_started, 3), "steps": counts["step/start"],
                    "tool_calls": counts["tool/call"], "tokens": tokens, "usage": usage, "events": result.events,
                })
                if not delivered:
                    report["stop_reason"] = f"terminal_{result.finish_reason}"
                    break
                report["answered_turns"] += 1
                report["stop_reason"] = "planned_turns_finished"
    except Exception as error:
        report.update(stop_reason="adapter_failure", error_type=type(error).__name__,
                      error=str(error).replace(key, "[redacted]"))
    finally:
        report["wall_seconds"] = round(monotonic() - started, 3)
        report["unexecuted_turns"] = len(prepared.turns) - report["requested_turns"]
        write_record(run / "report.json", report)
        seal(run)
    print(json.dumps(report, ensure_ascii=False))
    return int(report["stop_reason"] not in ("preflight_ok", "planned_turns_finished"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--harness-image", default=IMAGE)
    parser.add_argument("--check-only", action="store_true", help="Run offline tool and isolation preflight")
    parser.add_argument("--persistent-bash", action="store_true", help="Use the task shell and longds-bench skill")
    parser.add_argument("--memory-mb", type=int, help="Apply the same runtime memory limit as the paired agent")
    args = parser.parse_args()
    materials = args.materials.resolve()
    run = args.output.resolve()
    if run.is_relative_to(materials):
        parser.error("Provide a new output directory outside the sealed materials")
    if shutil.which("docker") is None or not SDK_SOURCE.is_dir():
        parser.error("Install Docker and prepare the DeepSeek Harness Python SDK")
    if args.check_only:
        if args.persistent_bash:
            parser.error("The filesystem preflight uses the per-command Bash tool contract")
        with harness_preflight.local_preflight() as probe:
            return run_task(materials, run, (probe.base_url, harness_preflight.MODEL, harness_preflight.KEY),
                            args.harness_image, probe=probe, memory_mb=args.memory_mb)
    env = {**dotenv_values(MODULE_DIR.parents[1] / ".env"), **os.environ}
    base_url = env.get("STRUCTURED_BASE_URL")
    model = env.get("STRUCTURED_MODEL")
    key = env.get("STRUCTURED_API_KEY")
    if not base_url or not model or not key:
        parser.error("Set STRUCTURED_BASE_URL, STRUCTURED_MODEL and STRUCTURED_API_KEY")
    return run_task(materials, run, (base_url, model, key), args.harness_image,
                    persistent_bash=args.persistent_bash, memory_mb=args.memory_mb)


if __name__ == "__main__":
    raise SystemExit(main())
