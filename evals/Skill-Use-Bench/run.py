"""Run the public PDF skill case through two real agent entry points."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
import io
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import tarfile
import traceback
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values
import yaml

from evals.longDS.longds_materials import seal, verify_seal
from evals.longDS.run_longds import _source_identity
from evals.deepseek_runtime import VERSION as DSH_VERSION
from evals.longDS.run_longds_harness import write_record
from evals.marathon.agents import extract_host_workspace, harness, personal
from evals.run_deepseek_harness import CHECKOUT
from evals.Toolathlon.runner import container, docker


ROOT = Path(__file__).resolve().parents[2]
CASE = "SF03_t1_merge_unordered"
REVISION = "1a80e93479e1a9f5ce4be2e27550edaf7f9d6ffc"
VOLUME_ROOT = "/workspace/skill-use-bench"
WORKSPACE = f"{VOLUME_ROOT}/work"


def committed_file(upstream: Path, name: str) -> bytes:
    return subprocess.check_output(["git", "-C", upstream, "show", f"{REVISION}:{name}"])


def prepare(upstream: Path, output: Path) -> str:
    source = "benchmark/pdftk-server"
    task_data = committed_file(upstream, f"{source}/tasks/t1_merge_unordered.yaml")
    task = yaml.safe_load(task_data)
    if task["task_id"] != CASE:
        raise ValueError("Unexpected upstream task identifier")
    docs = output / "seed" / "work" / "docs"
    docs.mkdir(parents=True)
    installed = output / "skills" / "pdftk-server"
    installed.mkdir(parents=True)
    (installed / "SKILL.md").write_bytes(committed_file(upstream, f"{source}/skill/skill.md"))
    (output / "official").mkdir()
    (output / "official" / "task.yaml").write_bytes(task_data)
    for destination, name in (
        ("rubric.yaml", f"{source}/rubrics/rubric_t1_merge_unordered.yaml"),
        ("score_trace.py", "benchmark/_scripts/score_trace.py"),
        ("verify_task_success.py", "benchmark/_scripts/verify_task_success.py"),
    ):
        (output / "official" / destination).write_bytes(committed_file(upstream, name))
    for item in task["initial_state"]["files"]:
        (docs / PurePosixPath(item["path"]).name).write_text(item["content"], encoding="utf-8", newline="\n")
    for item in task["initial_state"]["binary_assets"]:
        (docs / PurePosixPath(item["path"]).name).write_bytes(
            committed_file(upstream, f"{source}/assets/{CASE}/{item['path']}")
        )
    with tarfile.open(output / "seed.tar", "w") as archive:
        archive.add(docs.parent, arcname="work")
    write_record(output / "inputs.json", {
        "upstream": REVISION,
        "seed_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(docs.iterdir())},
        "skill_sha256": sha256((installed / "SKILL.md").read_bytes()).hexdigest(),
    })
    return task["description"]


@contextmanager
def workspace(image: str, seed: Path, output: Path, *, personal_side: bool):
    if personal_side:
        work = extract_host_workspace(seed, output / "native-workspace")
        docs = work / "docs"
        for item in docs.iterdir():
            item.chmod(0o444)
        docs.chmod(0o555)
        try:
            yield work
        finally:
            docs.chmod(0o755)
        return
    volume = docker("volume", "create", "skill-use-" + uuid4().hex)
    try:
        with container(
            image, "--user", "0:0", "--network", "none", "--read-only",
            "-w", "/volume", "--mount", f"type=volume,source={volume},target=/volume,volume-nocopy",
            "--mount", f"type=bind,source={seed},target=/seed.tar,readonly",
            command=("sh", "-ec", "tar -xf /seed.tar --no-same-owner; chmod -R a+rX,a-w work/docs; chown 65534:65534 work; chmod 0755 work"),
        ) as initializer:
            docker("start", "-a", initializer)
            code = docker("inspect", "--format", "{{.State.ExitCode}}", initializer)
            if code != "0":
                raise RuntimeError(f"PDF workspace initialization exited {code}")
        yield volume
    finally:
        docker("volume", "rm", volume)


def capture_pdfs(sandbox: str, output: Path) -> list[str]:
    names = docker("exec", sandbox, "find", ".", "-maxdepth", "1", "-type", "f", "-iname", "*.pdf", "-printf", "%f\\0")
    pdfs = [name for name in names.split("\0") if name]
    if any(PureWindowsPath(name).is_reserved() or any(char in name for char in "/\\:") for name in pdfs):
        raise ValueError("PDF output contains a filename unsafe to copy to the host")
    artifacts = output / "artifacts"
    artifacts.mkdir()
    if pdfs:
        data = subprocess.check_output(["docker", "exec", sandbox, "tar", "-cf", "-", "--", *pdfs])
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for member in archive.getmembers():
                if member.isfile() and member.name in pdfs:
                    with archive.extractfile(member) as pdf, (artifacts / member.name).open("xb") as dest:
                        shutil.copyfileobj(pdf, dest)
    return sorted(pdfs)


def host_input_hashes(work: Path) -> list[str]:
    return [f"{sha256(path.read_bytes()).hexdigest()}  docs/{path.name}"
            for path in sorted((work / "docs").iterdir()) if path.is_file() and not path.is_symlink()]


def capture_host_pdfs(work: Path, output: Path) -> list[str]:
    files = sorted(path for path in work.iterdir()
                   if path.suffix.casefold() == ".pdf" and path.is_file() and not path.is_symlink())
    artifacts = output / "artifacts"
    artifacts.mkdir()
    for path in files:
        shutil.copyfile(path, artifacts / path.name)
    return [path.name for path in files]



def run_side(side: str, args: argparse.Namespace, output: Path, prompt: str) -> dict:
    path = output / side
    path.mkdir()
    try:
        personal_side = side == "personal-agent"
        with workspace(args.image, output / "seed.tar", path, personal_side=personal_side) as bound:
            image = docker("image", "inspect", args.image, "--format", "{{.Id}}")
            if side == "personal-agent":
                scope = args.personal_skill_scope if args.personal_skill else None
                bundled = output / "skills" if scope == "bundled" else None
                home = output / "skill-home" if scope in {"project", "user"} else None
                project = output / "skill-project" if scope == "project" else None
                if home is not None:
                    shutil.copytree(output / "skills", home / ".agents/skills")
                if project is not None:
                    shutil.copytree(output / "skills", project / ".dsh/skills")
                driver = personal(
                    path, bound, args.model_env, args.postgres_image,
                    workspace=WORKSPACE, skill_root=bundled, user_skill_home=home, project_skill_root=project,
                    apply_benchmark_flags=not args.product_flags,
                )
            else:
                driver = harness(
                    path, args.harness_image, args.harness_sdk, args.model_env, bound,
                    workspace=WORKSPACE, skill_root=output / "skills",
                )
            with driver as active:
                if personal_side:
                    subprocess.run(("pdftk", "--version"), check=True, capture_output=True, timeout=15)
                    initial = host_input_hashes(bound)
                    delivery = active(1, prompt)
                    final = host_input_hashes(bound)
                    pdfs = capture_host_pdfs(bound, path)
                else:
                    submit, sandbox = active
                    docker("exec", sandbox, "sh", "-ec",
                           "test -w .; test ! -w docs; test ! -e /seed.tar; pdftk --version")
                    initial = docker("exec", sandbox, "sh", "-ec", "sha256sum docs/*").splitlines()
                    delivery = submit(1, prompt)
                    final = docker("exec", sandbox, "sh", "-ec", "sha256sum docs/* || true").splitlines()
                    pdfs = capture_pdfs(sandbox, path)
                write_record(path / "sandbox.json", {
                    "image": image, "input_hashes": initial, "final_input_hashes": final,
                })
                record = {"delivery": delivery.model_dump(), "pdfs": pdfs}
    except Exception as exc:
        (path / "runner-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        record = {"error": type(exc).__name__}
    write_record(path / "result.json", record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--harness-image", default="personal-agent-dsh-skill-use:local")
    parser.add_argument("--harness-sdk", type=Path, help="Root of the source checkout for the DeepSeek Python SDK")
    parser.add_argument("--model-env", type=Path, default=ROOT / ".env")
    parser.add_argument("--image", default="personal-agent-skill-use:local")
    parser.add_argument("--postgres-image", default="postgres:16-alpine")
    parser.add_argument("--personal-skill", action="store_true", help="Configure the native skill directory on the project Agent")
    parser.add_argument("--personal-skill-scope", choices=("project", "user", "bundled"), default="bundled")
    parser.add_argument("--agent", choices=("both", "personal-agent", "deepseek-harness"), default="both")
    parser.add_argument("--product-flags", action="store_true", help="Use configured product feature flags without benchmark overrides")
    args = parser.parse_args()
    for name in ("upstream", "output", "model_env"):
        setattr(args, name, getattr(args, name).resolve())
    args.harness_sdk = args.harness_sdk.resolve() if args.harness_sdk else CHECKOUT
    args.output.mkdir(parents=True)
    prompt = prepare(args.upstream, args.output)
    _source_identity(args.output)
    for path in (*Path(__file__).parent.glob("*.*"), ROOT / "evals/marathon/agents.py", ROOT / "evals/Toolathlon/runner.py",
                 *ROOT.joinpath("evals/longDS").glob("harness_*")):
        backup = args.output / "source-snapshot" / path.relative_to(ROOT)
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, backup)
    model_env = dotenv_values(args.model_env)
    sides = ("personal-agent", "deepseek-harness") if args.agent == "both" else (args.agent,)
    harness_identity = {}
    if "deepseek-harness" in sides:
        harness_identity = {
            "harness_version": DSH_VERSION,
            "harness_image": docker("image", "inspect", args.harness_image, "--format", "{{.Id}}"),
            "harness_sdk_checkout": subprocess.check_output(
                ["git", "-C", args.harness_sdk, "rev-parse", "HEAD"], text=True,
            ).strip(),
        }
    write_record(args.output / "run.json", {
        "task": CASE, "model": model_env.get("STRUCTURED_MODEL"),
        "provider_host": urlsplit(model_env.get("STRUCTURED_BASE_URL") or "").hostname,
        "agents": sides,
        "personal_skill": args.personal_skill,
        "personal_skill_scope": args.personal_skill_scope if args.personal_skill and "personal-agent" in sides else None,
        "product_feature_flags": args.product_flags,
        **harness_identity,
    })
    with ThreadPoolExecutor(max_workers=len(sides)) as workers:
        runs = {side: workers.submit(run_side, side, args, args.output, prompt) for side in sides}
        results = {side: run.result() for side, run in runs.items()}
    seal(args.output)
    verify_seal(args.output)
    return int(any("error" in result for result in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
