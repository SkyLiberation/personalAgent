"""Single-host, reentrant exclusion for one durable interaction's writers."""

from contextlib import contextmanager
import errno
import os
from pathlib import Path
from threading import Lock, RLock

from .errors import ConversationOperationConflict


class _RunLock:
    def __init__(self) -> None:
        self.lock = RLock()
        self.depth = 0


_registry_guard = Lock()
_registry: dict[str, _RunLock] = {}


@contextmanager
def exclusive_run_lock(key: str, path: Path | None):
    with _registry_guard:
        state = _registry.setdefault(key, _RunLock())
    if not state.lock.acquire(blocking=False):
        raise ConversationOperationConflict(
            "interaction run is already being processed"
        )
    stream = None
    try:
        if state.depth == 0 and path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = path.open("a+b")
            try:
                if os.name == "nt":
                    import msvcrt

                    if path.stat().st_size == 0:
                        stream.write(b"\0")
                        stream.flush()
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise ConversationOperationConflict(
                        "interaction run is already being processed"
                    ) from error
                raise
        state.depth += 1
        try:
            yield
        finally:
            state.depth -= 1
            if stream is not None:
                if os.name == "nt":
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        if stream is not None:
            stream.close()
        state.lock.release()
