"""Pytest plugin: stub out python-magic on broken Windows environments.

On this machine the only libmagic on PATH is Git-for-Windows' MSYS build
(``msys-magic-1.dll``), which crashes the (non-MSYS) Windows Python with a
native access violation when ``python-magic`` calls into it. That makes any test
importing ``unstructured`` (→ ``magic``) hang/crash — unrelated to app code.

Loaded via ``-p testing.magic_stub`` so the stub lands in ``sys.modules`` before
any real ``import magic`` happens. Only installs the stub when the real one is
unusable, so healthy CI/Linux environments are unaffected.
"""

from __future__ import annotations

import sys
import types


def _install_stub() -> None:
    if "magic" in sys.modules:
        return
    m = types.ModuleType("magic")

    def _detect(*_args, **_kwargs):
        return "text/plain"

    class Magic:  # noqa: D401 - minimal shim
        def __init__(self, *_args, **_kwargs):
            pass

        from_buffer = staticmethod(_detect)
        from_file = staticmethod(_detect)

    class _DetectResult:
        mime_type = "text/plain"
        name = "ASCII text"
        encoding = "utf-8"

    m.Magic = Magic
    m.from_buffer = _detect
    m.from_file = _detect
    m.detect_from_content = lambda *_a, **_k: _DetectResult()
    m.detect_from_filename = lambda *_a, **_k: _DetectResult()
    sys.modules["magic"] = m


def _real_magic_is_unusable() -> bool:
    """True when the only resolvable libmagic is the MSYS build (or none).

    Crucially this does NOT ``import magic`` — that import is what crashes — it
    replicates ``magic.loader`` candidate resolution via ctypes.util only.
    """
    if sys.platform not in ("win32", "cygwin"):
        return False
    from ctypes.util import find_library

    for name in ("magic", "libmagic", "magic1", "libmagic-1"):
        if find_library(name):
            return False  # a real Windows libmagic exists; leave it alone
    # Only msys-magic-1 (or nothing) is resolvable → unusable for Windows Python.
    return True


if _real_magic_is_unusable():
    _install_stub()

