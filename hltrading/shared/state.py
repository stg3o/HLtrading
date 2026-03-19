"""
hltrading.shared.state — shared JSON state persistence helpers.

These helpers centralize the file I/O mechanics used by multiple modules while
letting each caller preserve its own defaults and error-handling semantics.

save_state() uses an atomic write-then-rename pattern so a crash mid-write
can never corrupt the state file. The OS rename() call is atomic on POSIX
(Linux/macOS) — the old file stays intact until the new one is fully written.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable


def build_default_state(defaults: dict | Callable[[], dict] | None = None) -> dict:
    """Return a fresh default state dict from a mapping or factory."""
    if defaults is None:
        return {}
    if callable(defaults):
        return defaults()
    return copy.deepcopy(defaults)


def load_state(
    path: str | Path,
    *,
    defaults: dict | Callable[[], dict] | None = None,
    merge_defaults: bool = False,
    fallback_exceptions: Iterable[type[BaseException]] = (FileNotFoundError,),
) -> dict:
    """
    Load JSON state from ``path``.

    If an exception in ``fallback_exceptions`` occurs, returns a fresh default
    state instead. When ``merge_defaults`` is True, loaded values override the
    provided defaults while missing keys keep their default values.
    """
    default_state = build_default_state(defaults)
    handled = tuple(fallback_exceptions)
    try:
        with open(path) as f:
            loaded = json.load(f)
    except handled:
        return default_state

    if merge_defaults:
        default_state.update(loaded)
        return default_state
    return loaded


def save_state(
    path: str | Path,
    state: dict,
    *,
    indent: int = 2,
    json_default: Any = None,
) -> None:
    """
    Persist JSON state to ``path`` using an atomic write-then-rename.

    Writes to a sibling temp file first, then renames it over the target.
    A crash mid-write leaves the original file intact — the rename only
    happens after the new content is fully flushed to disk.
    """
    path = Path(path)
    payload = (
        json.dumps(state, indent=indent)
        if json_default is None
        else json.dumps(state, indent=indent, default=json_default)
    )
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".state_tmp_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
        os.replace(tmp_path, path)   # atomic on POSIX
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
