"""Compile trusted reads and literal edits for the existing task sandbox."""

from inspect import getsource
import json
from typing import Literal

from personal_agent.application.literal_replacement import replace_literal
from personal_agent.application.text_edit import LiteralTextEdit
from personal_agent.kernel.prompt_registry import PromptCatalog

from .models import BASH_TEMP_DIR, BashArgs, BashWorkspaceFileAction

WORKSPACE_VERSION_ENV = "PERSONAL_AGENT_WORKSPACE_VERSION"
_REPLACEMENT_SOURCE = getsource(replace_literal)


# This program runs inside the isolated Python image. Model-supplied input enters
# only as JSON data. Bash serializes commands and checks for surviving processes.
_WORKER = """
import json
import os
import stat
import tempfile
from hashlib import sha256
from pathlib import Path


def target(root, file_path):
    path = Path(file_path)
    if str(path) != file_path or path == Path(root) or not path.is_relative_to(root) or path.resolve(strict=True) != path:
        raise ValueError("use the canonical path to a non-symlink file in the task workspace")
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode):
        raise ValueError("use an existing regular UTF-8 file")
    return path, mode


def read(root, file_path, start_line, limit, start_column):
    path, _ = target(root, file_path)
    content = path.read_bytes()
    text = content.decode("utf-8").replace("\\r\\n", "\\n")
    lines = text.removesuffix("\\n").split("\\n") if text else []
    if start_line > max(1, len(lines)):
        raise ValueError(f"start_line is outside the file ({len(lines)} lines)")
    if start_column > len(lines[start_line - 1] if lines else "") + 1:
        raise ValueError("start_column is outside the first returned line")
    output = [f"{file_path} ({len(lines)} lines)"]
    remaining = 3000 - len(output[0])
    last = min(len(lines), start_line + limit - 1)
    next_line, next_column = last + 1, 1
    for number in range(start_line, last + 1):
        column = start_column if number == start_line else 1
        prefix = f"{number}: "
        line = lines[number - 1][column - 1:]
        count = min(len(line), max(0, remaining - len(prefix) - 1))
        if count or not line:
            output.append(prefix + line[:count])
        if count < len(line):
            next_line, next_column = number, column + count
            break
        remaining -= len(prefix) + count + 1
        if remaining <= 0:
            next_line = number + 1
            break
    if next_line <= len(lines):
        output.append(f"Continue with start_line={next_line}, start_column={next_column}.")
    print(sha256(content).hexdigest())
    print("\\n".join(output))


def edit(root, file_path, old_string, new_string, replace_all):
    expected = os.environ.get(VERSION_ENV)
    if expected is None:
        raise ValueError("FS_NOT_OBSERVED: Read the file with tool_read_file, then retry the edit.")
    try:
        path, mode = target(root, file_path)
        content = path.read_bytes()
    except FileNotFoundError:
        raise ValueError("FS_STALE_VERSION: File changed or disappeared; re-read it before editing.") from None
    if sha256(content).hexdigest() != expected:
        raise ValueError("FS_STALE_VERSION: File changed since it was read; re-read it with tool_read_file, then retry.")
    filesystem = os.statvfs(root)
    edited, count = replace_literal(content, old_string.encode("utf-8"), new_string.encode("utf-8"),
                                    replace_all, filesystem.f_bavail * filesystem.f_frsize)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(edited)
            os.fchmod(stream.fileno(), stat.S_IMODE(mode))
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(sha256(edited).hexdigest())
    print(json.dumps({"file_path": str(path), "replacements": count}, ensure_ascii=False))
"""


def workspace_edit_command(edit: LiteralTextEdit, *, prompts: PromptCatalog) -> BashArgs:
    return _compile("edit", edit.file_path, edit.model_dump(), prompts=prompts)


def workspace_read_command(file_path: str, *, start_line: int, limit: int, start_column: int,
                           prompts: PromptCatalog) -> BashArgs:
    return _compile("read", file_path,
                    {"file_path": file_path, "start_line": start_line, "limit": limit, "start_column": start_column},
                    prompts=prompts)


def _compile(operation: Literal["read", "edit"], file_path: str, arguments: dict[str, object], *,
             prompts: PromptCatalog) -> BashArgs:
    action = BashWorkspaceFileAction(operation=operation, file_path=file_path)
    data = json.dumps(arguments, ensure_ascii=True)
    command = (
        "python3 -I - <<'PERSONAL_AGENT_FILE'\n"
        f"{_WORKER}\n"
        f"{_REPLACEMENT_SOURCE}\n"
        f"VERSION_ENV = {WORKSPACE_VERSION_ENV!r}\n"
        f"args = json.loads({data!r})\n"
        "try:\n"
        f"    {action.operation}({BASH_TEMP_DIR!r}, **args)\n"
        "except (OSError, ValueError, RuntimeError) as error:\n"
        "    raise SystemExit(str(error))\n"
        "PERSONAL_AGENT_FILE"
    )
    return BashArgs.model_validate(
        {"command": command, "description": f"{operation.title()} a task workspace file",
         "workspace_file": action},
        context=prompts,
    )
