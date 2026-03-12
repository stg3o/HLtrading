"""
hltrading.shared.state — shared JSON state persistence helpers.

These helpers centralize the file I/O mechanics used by multiple modules while
letting each caller preserve its own defaults and error-handling semantics.
"""
from __future__ import annotations

import copy
import json
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
    """Persist JSON state to ``path`` with caller-controlled serialization."""
    with open(path, "w") as f:
        if json_default is None:
            json.dump(state, f, indent=indent)
        else:
            json.dump(state, f, indent=indent, default=json_default)
