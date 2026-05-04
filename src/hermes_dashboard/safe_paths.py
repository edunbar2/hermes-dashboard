"""Filesystem path helpers for dashboard-controlled file access.

All helpers resolve roots and children before returning a path. This makes
path traversal protections explicit for static/profile/state paths and keeps
SAST tools from treating route parameters or environment-derived roots as
implicitly trusted filesystem paths.
"""
from __future__ import annotations

from pathlib import Path


def resolve_root(root: Path) -> Path:
    """Return an absolute, resolved root directory path."""
    return Path(root).expanduser().resolve()


def resolve_child(root: Path, *parts: str | Path) -> Path:
    """Resolve ``parts`` under ``root`` and reject escapes.

    Raises:
        ValueError: if the resolved child does not remain under the resolved
            root directory.
    """
    safe_root = resolve_root(root)
    child = safe_root.joinpath(*parts).resolve()
    try:
        child.relative_to(safe_root)
    except ValueError as exc:
        raise ValueError(f"path escapes configured root: {child}") from exc
    return child
