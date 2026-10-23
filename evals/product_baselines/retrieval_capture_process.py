"""绑定正式采集的实际解释器；Windows venv 包装进程不是停止证据。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
from time import monotonic

from pydantic import BaseModel, ConfigDict, Field


class ServerProcessIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    pid: int = Field(gt=0)
    parent_pid: int = Field(gt=0)


def record_server_process(path: Path) -> None:
    identity = ServerProcessIdentity(pid=os.getpid(), parent_pid=os.getppid())
    with path.open("x", encoding="utf-8") as stream:
        stream.write(identity.model_dump_json())


class ActualWebProcess:
    """Keep the Windows handle open from identity binding through final collection."""

    def __init__(self, launcher: subprocess.Popen, path: Path) -> None:
        self.launcher = launcher
        self.identity = ServerProcessIdentity.model_validate_json(path.read_bytes())
        identity = self.identity
        if not (
            identity.pid == launcher.pid and identity.parent_pid == os.getpid()
            or identity.parent_pid == launcher.pid and identity.pid != os.getpid()
        ):
            raise ValueError("实际Web解释器不属于本次Popen进程")
        self._handle = None
        self._kernel = None
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
            kernel.TerminateProcess.restype = wintypes.BOOL
            kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            kernel.GetExitCodeProcess.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle.restype = wintypes.BOOL
            self._handle = kernel.OpenProcess(0x100000 | 0x1000 | 0x0001, False, identity.pid)
            if not self._handle:
                raise ctypes.WinError(ctypes.get_last_error())
            self._kernel = kernel
        elif identity.pid != launcher.pid:
            raise ValueError("本平台实际解释器必须为本次Popen进程")

    def poll(self) -> int | None:
        if self._kernel is None:
            return self.launcher.poll()
        status = self._kernel.WaitForSingleObject(self._handle, 0)
        if status == 258:
            return None
        if status != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not self._kernel.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value

    def stop(self, *, deadline: float) -> None:
        if self.poll() is None:
            if self._kernel is not None:
                if not self._kernel.TerminateProcess(self._handle, 124):
                    raise ctypes.WinError(ctypes.get_last_error())
                remaining_ms = int(max(0, min(10, deadline - monotonic())) * 1000)
                if self._kernel.WaitForSingleObject(self._handle, remaining_ms) != 0:
                    raise RuntimeError("实际Web解释器停止未确认")
            else:
                self.launcher.terminate()
        try:
            self.launcher.wait(timeout=max(0, min(10, deadline - monotonic())))
        except subprocess.TimeoutExpired:
            self.launcher.kill()
            self.launcher.wait(timeout=max(0, deadline - monotonic()))

    def close(self) -> None:
        if self._handle is not None:
            if not self._kernel.CloseHandle(self._handle):
                raise ctypes.WinError(ctypes.get_last_error())
            self._handle = None
