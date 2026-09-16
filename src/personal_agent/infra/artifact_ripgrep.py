"""Run a fixed ripgrep executable on authorized stdin; never invoke a shell."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading

from personal_agent.application.conversation.artifact_search import TextMatch


class RipgrepArtifactSearch:
    def __init__(self, *, executable: str | None = None, timeout_seconds: float = 10,
                 max_output_bytes: int = 8 * 1024 * 1024):
        self._executable = executable or shutil.which("rg")
        self._timeout = timeout_seconds
        self._max_output_bytes = max_output_bytes

    def find(self, text: str, *, keyword: str, regex: bool) -> tuple[TextMatch, ...]:
        if not self._executable:
            raise RuntimeError("未安装 ripgrep，无法执行正文搜索。")
        args = [self._executable, "--json", "--no-config", "--text", "--multiline", "--ignore-case"]
        if not regex:
            args.append("--fixed-strings")
        args.extend(["--regexp", keyword, "--", "-"])
        expired = threading.Event()
        output = bytearray()
        # Anonymous temporary descriptors: no model-controlled path or retained projection.
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as errors:
            source.write(text.encode("utf-8"))
            source.seek(0)
            with subprocess.Popen(args, stdin=source, stdout=subprocess.PIPE, stderr=errors,
                                  shell=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0) as process:
                def expire():
                    expired.set()
                    process.kill()
                timer = threading.Timer(self._timeout, expire)
                timer.start()
                try:
                    while chunk := process.stdout.read1(65536):
                        output.extend(chunk)
                        if len(output) > self._max_output_bytes:
                            raise RuntimeError("搜索引擎输出超过容量，未返回不完整匹配；请缩小搜索表达式。")
                    code = process.wait()
                    if expired.is_set():
                        raise TimeoutError("正文搜索超时，未将未完成搜索解释为零匹配。")
                    if code not in (0, 1):
                        errors.seek(0)
                        raise ValueError("搜索表达式或引擎执行失败：" + errors.read(4096).decode("utf-8", errors="replace"))
                finally:
                    timer.cancel()
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    timer.join()
        matches = []
        for line in output.splitlines():
            event = json.loads(line)
            if event["type"] != "match":
                continue
            data = event["data"]
            for submatch in data["submatches"]:
                matches.append(TextMatch(start=data["absolute_offset"] + submatch["start"],
                                         end=data["absolute_offset"] + submatch["end"]))
        return tuple(matches)
