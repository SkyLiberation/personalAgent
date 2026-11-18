"""Copy prepared Toolathlon workspace originals into Conversation attachments."""

from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
from tempfile import TemporaryFile
from typing import BinaryIO, cast
import zipfile

from evals.conversation_http import upload_attachments
from personal_agent.application.artifacts.models import validate_display_filename
from personal_agent.kernel.contracts.resource import ResourceRef


WORKSPACE = "/workspace/dumps/workspace"
_INDIVIDUAL_ATTACHMENT_LIMIT = 32
# Toolathlon uses some agent-workspace entries to carry service credentials or benchmark state.
_EXCLUDED = (
    ".git", ".gitkeep", ".env", ".hf_token", ".github_token", "hf_token.txt", "k8s_configs",
    "memory", "evaluation", "groundtruth_workspace",
)


def _individual_files(paths: list[PurePosixPath]) -> bool:
    if len(paths) > _INDIVIDUAL_ATTACHMENT_LIMIT or len({path.name.casefold() for path in paths}) != len(paths):
        return False
    try:
        for path in paths:
            validate_display_filename(path.name)
    except ValueError:
        return False
    return True


def _attachments(
    files: dict[PurePosixPath, Callable[[], BinaryIO]], output: Path,
) -> Iterator[tuple[PurePosixPath, BinaryIO]]:
    paths = sorted(files)
    if _individual_files(paths):
        for path in paths:
            with files[path]() as source:
                yield path, source
        return
    with TemporaryFile(dir=output) as bundle:
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as packaged:
            for path in paths:
                with files[path]() as source, packaged.open(path.as_posix(), "w") as target:
                    shutil.copyfileobj(source, target)
        bundle.seek(0)
        yield PurePosixPath("toolathlon-workspace.zip"), bundle


def _gateway_files(container: str, output: Path) -> Iterator[tuple[PurePosixPath, BinaryIO]]:
    # Keep paths in the archive. Extracting them on the host would depend on Windows filename rules.
    with TemporaryFile(dir=output) as snapshot:
        subprocess.run(
            ("docker", "exec", container, "tar", *(f"--exclude={name}" for name in _EXCLUDED),
             "-C", WORKSPACE, "-cf", "-", "."),
            stdout=snapshot, timeout=180, check=True,
        )
        snapshot.seek(0)
        with tarfile.open(fileobj=snapshot, mode="r:") as archive:
            files: dict[PurePosixPath, Callable[[], BinaryIO]] = {}
            for item in archive:
                if not item.isfile():
                    continue
                path = PurePosixPath(item.name)
                if path.is_absolute() or ".." in path.parts or path in files:
                    raise ValueError("Invalid file path in Toolathlon workspace snapshot")
                files[path] = cast(Callable[[], BinaryIO], partial(archive.extractfile, item))
            yield from _attachments(files, output)


def upload_local_workspace_attachments(
    base: str, workspace: Path, output: Path, *, user_id: str | None = None, api_key: str | None = None,
) -> tuple[ResourceRef, ...]:
    if not workspace.is_dir():
        raise FileNotFoundError(workspace)
    files = {}
    for source in workspace.rglob("*"):
        path = PurePosixPath(source.relative_to(workspace).as_posix())
        if source.is_file() and not source.is_symlink() and not any(part in _EXCLUDED for part in path.parts):
            files[path] = partial(source.open, "rb")
    return upload_attachments(
        base, _attachments(files, output), manifest=output / "fixture-uploads.json", user_id=user_id, api_key=api_key,
    )


def upload_gateway_attachments(
    base: str, container: str, output: Path, *, user_id: str,
) -> tuple[ResourceRef, ...]:
    return upload_attachments(
        base, _gateway_files(container, output), manifest=output / "fixture-uploads.json", user_id=user_id,
    )
