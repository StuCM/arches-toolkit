"""Tests for ``arches-toolkit init`` helpers — image-flag validation and the
arches version pin. The docker-running paths are exercised by manual smoke
testing; these cover the pure logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from arches_toolkit.commands.init import (
    _pin_arches_dependency,
    _validate_image_repo,
)


# --------------------------------------------------------------------------- #
# _validate_image_repo
# --------------------------------------------------------------------------- #


def test_image_repo_plain_ok():
    assert _validate_image_repo("ghcr.io/flaxandteal/arches-toolkit") == (
        "ghcr.io/flaxandteal/arches-toolkit"
    )


def test_image_repo_registry_port_ok():
    """A colon before a slash is a registry port, not a tag."""
    assert _validate_image_repo("localhost:5000/arches-toolkit") == (
        "localhost:5000/arches-toolkit"
    )


def test_image_repo_with_tag_rejected():
    """A tag inside --arches-toolkit-image would join with the tag flag into
    a double-colon reference — reject with the corrected flags spelled out."""
    with pytest.raises(typer.BadParameter, match="--arches-toolkit-tag v8.2.0a4-v1"):
        _validate_image_repo("ghcr.io/flaxandteal/arches-base:v8.2.0a4-v1")


def test_image_repo_bare_name_with_tag_rejected():
    with pytest.raises(typer.BadParameter, match="must not include a tag"):
        _validate_image_repo("arches-toolkit:dev")


# --------------------------------------------------------------------------- #
# _pin_arches_dependency
# --------------------------------------------------------------------------- #


PYPROJECT = """\
[project]
name = "my-project"
version = "0.0.1"
dependencies = [
    "arches>=8.2.0,<8.3.0",
    "requests>=2.0",
]
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "pyproject.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_pin_rewrites_template_range(tmp_path: Path):
    """The template's anticipated-final range is unsatisfiable while only
    pre-releases exist (PEP 440: 8.2.0a4 < 8.2.0) — pin to the base image's
    actual dist version."""
    p = _write(tmp_path, PYPROJECT)
    status = _pin_arches_dependency(p, "8.2.0a4")
    assert "pinned" in status
    text = p.read_text(encoding="utf-8")
    assert '"arches==8.2.0a4"' in text
    assert "arches>=8.2.0" not in text
    # other deps untouched
    assert '"requests>=2.0"' in text


def test_pin_is_idempotent(tmp_path: Path):
    p = _write(tmp_path, PYPROJECT)
    _pin_arches_dependency(p, "8.2.0a4")
    before = p.read_text(encoding="utf-8")
    status = _pin_arches_dependency(p, "8.2.0a4")
    assert "already pinned" in status
    assert p.read_text(encoding="utf-8") == before


def test_pin_does_not_match_prefixed_packages(tmp_path: Path):
    """`arches-her` etc. must not be mistaken for core arches."""
    p = _write(
        tmp_path,
        PYPROJECT.replace('"arches>=8.2.0,<8.3.0",', '"arches-her>=2.0",'),
    )
    status = _pin_arches_dependency(p, "8.2.0a4")
    assert "no arches dependency" in status
    assert '"arches-her>=2.0"' in p.read_text(encoding="utf-8")


def test_pin_missing_pyproject(tmp_path: Path):
    status = _pin_arches_dependency(tmp_path / "pyproject.toml", "8.2.0a4")
    assert "not found" in status
