"""Tests for the install-script construction. The actual `install` command
shells out to `docker compose` and isn't unit-tested here — that's covered
by manual smoke testing against a real project."""

from __future__ import annotations

from pathlib import Path

from arches_toolkit.apps_manifest import AppEntry
from arches_toolkit.commands.install import _build_install_script


def _project(tmp_path: Path) -> Path:
    """Create a project_root under tmp_path so workspace = tmp_path."""
    p = tmp_path / "project"
    p.mkdir()
    return p


def test_install_script_no_develop_apps(tmp_path: Path) -> None:
    script = _build_install_script([], _project(tmp_path))
    lines = script.splitlines()
    assert lines[0] == "set -eu"
    assert any("uv pip install" in line and "-e ." in line for line in lines)
    assert "/workspace" not in script


def test_install_script_verbose_traces_commands(tmp_path: Path) -> None:
    """--verbose turns on shell tracing inside the container script."""
    script = _build_install_script([], _project(tmp_path), verbose=True)
    assert script.splitlines()[0] == "set -eux"


def test_install_script_includes_prerelease_allow(tmp_path: Path) -> None:
    """The whole flow assumes pre-releases are OK — bake it in."""
    script = _build_install_script([], _project(tmp_path))
    assert "--prerelease=allow" in script


def test_install_script_skips_develop_app_with_no_local_clone(tmp_path: Path) -> None:
    """Without a sibling clone, pyproject's `pkg @ git+repo@ref` install
    handles the develop app — install does NOT try to install editable
    from a path that doesn't exist."""
    script = _build_install_script(
        [AppEntry(package="arches-her", source="git",
                  repo="https://github.com/x/arches-her.git", mode="develop")],
        _project(tmp_path),
    )
    assert "/workspace" not in script


def test_install_script_force_reinstalls_develop_app_with_local_clone(tmp_path: Path) -> None:
    """When the sibling clone exists, install force-reinstalls editable so
    the local working tree overrides whatever pyproject installed from git."""
    project = _project(tmp_path)
    (tmp_path / "arches-her").mkdir()
    script = _build_install_script(
        [AppEntry(package="arches-her", source="git",
                  repo="https://github.com/x/arches-her.git", mode="develop")],
        project,
    )
    assert "--force-reinstall -e /workspace/arches-her" in script


def test_install_script_uses_path_override_for_clone_dir(tmp_path: Path) -> None:
    """Develop entries with explicit `path:` install from /workspace/<path>,
    matching the sibling-dir convention shared with switch-mode/clone."""
    project = _project(tmp_path)
    (tmp_path / "2.0.x").mkdir()
    script = _build_install_script(
        [AppEntry(package="arches-her", source="git",
                  repo="https://github.com/x/arches-her.git",
                  mode="develop", path="2.0.x")],
        project,
    )
    assert "-e /workspace/2.0.x" in script
    assert "-e /workspace/arches-her" not in script
