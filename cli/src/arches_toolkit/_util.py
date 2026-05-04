"""Shared helpers used across commands.

Kept separate from ``commands.*`` so helpers can be imported without pulling
in Typer (cheap imports, easier testing).
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

import typer

PACKAGE_DATA = "arches_toolkit._data"

_IDENT_RE = re.compile(r"[a-z][a-z0-9_]*")
_EXTERNAL_NAME_RE = re.compile(r"[a-z][a-z0-9_-]*")


def validate_name(name: str, *, what: str = "name") -> str:
    """Return ``name`` iff it is a lowercase snake_case Python identifier."""
    if not _IDENT_RE.fullmatch(name):
        raise typer.BadParameter(
            f"{what} {name!r} must start with a lowercase letter and contain "
            "only lowercase letters, digits, and underscores"
        )
    return name


def validate_external_name(name: str, *, what: str = "name") -> str:
    """Return ``name`` iff it's a lowercase kebab- or snake-case identifier.

    For project/distribution/app names that appear as directory names or PyPI
    distribution names — both allow hyphens, unlike Python module names.
    Convert to a Python identifier via :func:`to_python_identifier`.
    """
    if not _EXTERNAL_NAME_RE.fullmatch(name):
        raise typer.BadParameter(
            f"{what} {name!r} must start with a lowercase letter and contain "
            "only lowercase letters, digits, hyphens, and underscores"
        )
    return name


def to_python_identifier(name: str) -> str:
    """Convert a kebab-case external name to a snake_case Python identifier."""
    return name.replace("-", "_")


def package_data_path(name: str) -> Path:
    """Resolve a path inside ``arches_toolkit._data`` shipped as package data."""
    p = Path(str(resources.files(PACKAGE_DATA).joinpath(name)))
    if not p.exists():
        raise typer.BadParameter(f"package data missing: {name}")
    return p
