"""Launch a benchmark's isolated Linux workspace with the official DeepSeek SDK."""

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from evals.run_deepseek_harness import sha256


VERSION = "0.2.2-rc.5"
ENTRY = "/opt/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js"
KEY_ENV = "DSH_EVAL_PROVIDER_KEY"


def write_profile(
    directory: Path, *, workspace: str, provider: str, model: str, base_url: str,
    persona: str, window: int, output_limit: int, step_limit: int,
    file_tools: bool = True, skill: bool = False, persistent_bash: bool = False,
) -> Path:
    def change(id: str, **config: object) -> dict:
        return {"id": id, "config": config}

    def add(id: str, **config: object) -> dict:
        return {"id": id, "name": f"@deepseek-ai/dsh-{id}", "config": config}

    plugins = [
        add("llm-pi-ai", providers={provider: {
            "api": "openai-completions", "baseURL": base_url, "apiKeyEnv": KEY_ENV,
            "reasoning": "medium", "retryPolicy": {"mode": "normal", "maxRetries": 2},
            "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": True},
            "models": [{"id": model, "contextWindow": window, "maxTokens": output_limit,
                        "reasoningEfforts": {"medium": "medium"}}],
        }}),
        add("fs-sandbox"),
        add("shell-env"),
    ]
    if not persistent_bash:
        plugins.extend((
            add("bash-sandbox", cwd=workspace, timeoutMs=60_000, maxTimeoutMs=60_000),
            add("tool-bash", enableRunInBackground=False, promoteOnTimeout=False),
        ))
    plugins.append({"id": "step-limit", "name": "/dsh-config/step-limit.mjs", "config": {"limit": step_limit}})
    if skill:
        plugins.extend((
            add("skill"),
            add("skill-filesystem", includeDefaultRoots=False, bundledSkillDir="/dsh-skills", watch=False),
            add("tool-skill"),
        ))
    rows = [
        *({"id": id, "disabled": True} for id in (
            "persistent-pwsh", "terminal-pwsh", "llm-deepseek", "tool-working-directory",
            *(("persistent-bash", "terminal-bash") if not persistent_bash else ()),
        )),
        change("sandbox", runnerCommand=["/usr/bin/bwrap", "--unshare-net"], runnerFailureSignatures=["bwrap:"]),
        change("sandbox-policy", mode="workspace-write", workspaceRoot=workspace, additionalWritableRoots=["/tmp"]),
        change("working-directory", defaultDirectory=workspace),
        change("tool-fs", read=file_tools, write=file_tools, edit=file_tools, readImage=False, applyPatch=False),
        change("system-prompt", personaPrefix=persona, includeHarnessIdentity=False, includeRuntimeContext=False),
        change("sessions", root="/dsh-records/sessions", compression="none"),
        {"insert": plugins},
    ]
    if persistent_bash:
        rows.insert(0, change("persistent-bash", timeoutMs=60_000))
    directory.mkdir()
    source = Path(__file__).with_name("longDS") / "harness_step_limit.mjs"
    (directory / "step-limit.mjs").write_bytes(source.read_bytes())
    profile = directory / "cordis.json"
    profile.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return profile


@contextmanager
def native_runtime(
    output: Path, profile: Path, sdk_source: Path, *, image: str, workspace: str, mounts: tuple[str, ...],
    provider: str, model: str, provider_key: str, output_limit: int, timeout: int, memory_mb: int,
) -> Iterator[tuple[object, str]]:
    from evals.Toolathlon.runner import docker

    sys.path.insert(0, str(sdk_source))
    from deepseek_harness import DeepSeekHarness
    from deepseek_harness.models import InitializeResponse

    class LinuxHarness(DeepSeekHarness):
        """Initialize with the runtime's POSIX path over the SDK's RPC transport."""

        def start(self) -> None:
            if not self._initialized:
                self.client.start()
                self.client.request("initialize", {
                    "cwd": workspace, "provider": provider, "model": model,
                    "reasoningEffort": "medium", "maxTokens": output_limit,
                }, response_model=InitializeResponse, timeout_seconds=self.client.config.initialize_timeout_seconds)
                self._initialized = True

    name = f"dsh-eval-{uuid4().hex}"
    image_id = docker("image", "inspect", "--format", "{{.Id}}", image)
    config = profile.parent
    records = output / "runtime-records"
    records.mkdir()
    records.chmod(0o777)
    credential = config / "provider.env"
    credential.write_text(f"{KEY_ENV}={json.dumps(provider_key)}\n", encoding="utf-8")
    bindings = tuple(arg for mount in mounts for arg in ("--mount", mount))
    try:
        with LinuxHarness(
            cwd=str(output), runtime_cwd=str(output), provider=provider, model=model,
            request_timeout_seconds=timeout, shutdown_timeout_seconds=20,
            _launch_args=(
                "docker", "run", "--rm", "-i", "--name", name, "--user", "65534:65534", "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--security-opt", "seccomp=unconfined", "--ipc", "none", "--pids-limit", "64",
                "--memory", f"{memory_mb}m", "--memory-swap", f"{memory_mb}m", "--cpus", "1",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777", "--workdir", workspace,
                "--env", "HOME=/tmp", "--env", "DSH_HOME=/dsh-records/dsh-home",
                "--env", "NARB_DISABLE_NATIVE_CACHE=1",
                "--mount", f"type=bind,source={config},target=/dsh-config,readonly",
                "--mount", f"type=bind,source={records},target=/dsh-records", *bindings,
                "--entrypoint", "/usr/local/bin/node", image_id,
                "--env-file=/dsh-config/provider.env", ENTRY, "--profile", "sdk-minimal",
                "--patch", f"/dsh-config/{profile.name}",
            ),
        ) as runtime:
            credential.unlink()
            info = json.loads(docker("inspect", name))[0]
            executable = docker("exec", name, "readlink", "/proc/1/exe")
            if info["Path"] != "/usr/local/bin/node" or executable != info["Path"]:
                raise ValueError("Unexpected DeepSeek Harness container entrypoint")
            version = docker("exec", name, executable, "-p",
                             "require('/opt/dsh/node_modules/@deepseek-ai/dsh/package.json').version")
            if version != VERSION:
                raise ValueError(f"Expected DeepSeek Harness {VERSION}, found {version}")
            (output / "harness-runtime.json").write_text(json.dumps({
                "version": version, "image": image_id, "container_id": info["Id"],
                "entrypoint": info["Path"], "profile_sha256": sha256(profile),
                "sdk_api_sha256": sha256(sdk_source / "deepseek_harness/api.py"),
                "tool_sandbox": "native-bwrap-unshare-net",
            }, indent=2), encoding="utf-8")
            yield runtime, name
    finally:
        credential.unlink(missing_ok=True)
        removed = subprocess.run(("docker", "rm", "-f", name), capture_output=True, text=True, timeout=20)
        if removed.returncode and "no such container" not in removed.stderr.casefold():
            raise RuntimeError(f"Failed to remove DeepSeek Harness container {name}")
