"""Artifact-local process exclusion and durable immutable file installation."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time
from typing import Iterator
from uuid import uuid4


@contextmanager
def exclusive_artifact_lock(path: Path, *, create: bool = True) -> Iterator[None]:
    """OS locks release on process death; lock files are not acceptance facts."""
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b" if create else "r+b") as lock:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                if not create:
                    raise RuntimeError("Artifact producer lock is incomplete")
                lock.write(b"\0")
                lock.flush()
            while True:
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def install_immutable(path: Path, content: bytes) -> None:
    """Publish complete bytes once, never overwrite a bound immutable file."""
    if path.exists():
        if path.read_bytes() != content:
            raise RuntimeError("InvariantViolation: immutable Artifact file differs")
        return
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise RuntimeError(
                    "InvariantViolation: immutable Artifact file differs"
                )
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
