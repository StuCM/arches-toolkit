"""Tests for ``arches-toolkit list``. Render to a captured Console so we can
assert on the visible text — the table styling itself is rich's job."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
import yaml
from rich.console import Console

from arches_toolkit.apps_manifest import AppEntry
from arches_toolkit.commands import list_apps as list_apps_mod
from arches_toolkit.commands.list_apps import (
    _install_state,
    _ref_for_display,
    _source_for_display,
    list_apps,
)


# --------------------------------------------------------------------------- #
# Per-row helpers
# --------------------------------------------------------------------------- #


def test_install_state_release_pypi(tmp_path: Path) -> None:
    entry = AppEntry(package="arches-foo", source="pypi", mode="release")
    assert _install_state(entry, tmp_path / "project") == "pypi"


def test_install_state_release_git(tmp_path: Path) -> None:
    entry = AppEntry(
        package="arches-foo", source="git",
        repo="https://github.com/x/arches-foo.git", mode="release",
    )
    assert "git" in _install_state(entry, tmp_path / "project")


def test_install_state_develop_no_clone(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    entry = AppEntry(
        package="arches-foo", source="git",
        repo="https://github.com/x/arches-foo.git", mode="develop",
    )
    state = _install_state(entry, project)
    assert "team branch" in state
    assert "editable" not in state


def test_install_state_develop_with_clone(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "arches-foo").mkdir()
    entry = AppEntry(
        package="arches-foo", source="git",
        repo="https://github.com/x/arches-foo.git", mode="develop",
    )
    assert "editable" in _install_state(entry, project)


def test_ref_for_display_default_for_develop_when_absent() -> None:
    entry = AppEntry(
        package="arches-foo", source="git",
        repo="https://x/x.git", mode="develop",
    )
    out = _ref_for_display(entry)
    assert "main" in out
    assert "default" in out


def test_ref_for_display_explicit_value_used() -> None:
    entry = AppEntry(
        package="arches-foo", source="git",
        repo="https://x/x.git", ref="feature/wip", mode="develop",
    )
    assert _ref_for_display(entry) == "feature/wip"


def test_ref_for_display_release_no_ref_renders_dash() -> None:
    entry = AppEntry(package="arches-foo", source="pypi", mode="release")
    assert "-" in _ref_for_display(entry)


def test_source_for_display_includes_repo_when_present() -> None:
    entry = AppEntry(
        package="arches-foo", source="git",
        repo="https://github.com/x/arches-foo.git", mode="release",
    )
    assert "https://github.com/x/arches-foo.git" in _source_for_display(entry)


def test_source_for_display_pypi_alone() -> None:
    entry = AppEntry(package="arches-foo", source="pypi", mode="release")
    assert _source_for_display(entry) == "pypi"


def test_source_for_display_develop_annotates_release_origin() -> None:
    # A pypi-source app in develop mode installs git+clone, not pypi — the
    # source is only the release origin, so the column must say so rather than
    # bare "pypi" next to an editable install.
    entry = AppEntry(
        package="arches-foo", source="pypi",
        repo="https://github.com/x/arches-foo.git", mode="develop",
    )
    out = _source_for_display(entry)
    assert "release origin" in out
    assert "pypi" in out
    assert "arches-foo.git" in out


# --------------------------------------------------------------------------- #
# End-to-end: list_apps prints sensible content
# --------------------------------------------------------------------------- #


def _write_manifest(project: Path, entries: list[dict]) -> Path:
    p = project / "apps.yaml"
    p.write_text(yaml.safe_dump({"apps": entries}, sort_keys=False))
    return p


def test_list_apps_missing_manifest_errors(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(typer.BadParameter, match="not found"):
        list_apps(manifest_path=project / "apps.yaml", project_root=project)


def test_list_apps_empty_manifest_prints_hint(tmp_path: Path, monkeypatch, capsys) -> None:
    project = tmp_path / "project"
    project.mkdir()
    manifest = _write_manifest(project, [])
    # Force rich to render to plain captured stdout (no colour).
    monkeypatch.setattr(
        list_apps_mod, "Console", lambda *a, **kw: Console(force_terminal=False, no_color=True),
    )
    list_apps(manifest_path=manifest, project_root=project)
    out = capsys.readouterr().out
    assert "no apps yet" in out


def test_list_apps_renders_rows_for_each_app(tmp_path: Path, monkeypatch, capsys) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "arches-her").mkdir()  # cloned develop sibling
    manifest = _write_manifest(project, [
        {"package": "arches-foo", "source": "pypi", "version": "~=1.0", "mode": "release"},
        {"package": "arches-her", "source": "git",
         "repo": "https://github.com/x/arches-her.git",
         "ref": "feature/wip", "mode": "develop"},
        {"package": "arches-bar", "source": "git",
         "repo": "https://github.com/x/arches-bar.git",
         "mode": "develop"},  # no clone, default ref
    ])
    monkeypatch.setattr(
        list_apps_mod, "Console",
        lambda *a, **kw: Console(force_terminal=False, no_color=True, width=200),
    )
    list_apps(manifest_path=manifest, project_root=project)
    out = capsys.readouterr().out

    # All packages appear
    assert "arches-foo" in out
    assert "arches-her" in out
    assert "arches-bar" in out

    # Mode markers
    assert "release" in out
    assert "develop" in out

    # Refs rendered: explicit + default
    assert "feature/wip" in out
    assert "main" in out  # default for arches-bar

    # Cloned column: arches-her has a sibling, others don't
    assert "✓" in out

    # Install states
    assert "editable" in out  # arches-her
    assert "team branch" in out  # arches-bar
    assert "pypi" in out  # arches-foo

    # Footer summarises develop count
    assert "1/2 cloned" in out
