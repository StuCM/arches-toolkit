"""Tests for the install-script construction. The actual `install` command
shells out to `docker compose` and isn't unit-tested here — that's covered
by manual smoke testing against a real project."""

from __future__ import annotations

from pathlib import Path

from arches_toolkit.apps_manifest import AppEntry
import json

from arches_toolkit.commands.install import (
    _build_install_script,
    _build_npm_script,
    _npm_overlay_specs,
)


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


# --------------------------------------------------------------------------- #
# npm overlay (local clone deps, --no-save)
# --------------------------------------------------------------------------- #


def test_npm_overlay_reads_clone_dependencies(tmp_path: Path) -> None:
    project = _project(tmp_path)
    clone = tmp_path / "arches-foo"
    clone.mkdir()
    (clone / "package.json").write_text(
        json.dumps({"name": "arches-foo", "dependencies": {"leaflet": "^1.9.0"}}),
        encoding="utf-8",
    )
    specs = _npm_overlay_specs(
        [AppEntry(package="arches-foo", source="git",
                  repo="https://github.com/x/arches-foo.git",
                  mode="develop", npm=True)],
        project,
    )
    assert specs == ["leaflet@^1.9.0"]


def test_npm_overlay_skips_non_npm_and_cloneless(tmp_path: Path) -> None:
    project = _project(tmp_path)
    clone = tmp_path / "arches-foo"
    clone.mkdir()
    (clone / "package.json").write_text('{"dependencies": {"x": "1"}}', encoding="utf-8")
    entries = [
        AppEntry(package="arches-foo", source="git",
                 repo="https://github.com/x/arches-foo.git",
                 mode="develop", npm=False),
        AppEntry(package="arches-bar", source="git",
                 repo="https://github.com/x/arches-bar.git",
                 mode="develop", npm=True),
    ]
    assert _npm_overlay_specs(entries, project) == []


def test_npm_script_reconciles_then_overlays_then_stamps() -> None:
    script = _build_npm_script(["leaflet@^1.9.0"])
    lines = script.splitlines()
    assert lines[0] == "set -eu"
    committed = next(i for i, line in enumerate(lines) if line == "npm install --no-audit --no-fund")
    overlay = next(i for i, line in enumerate(lines) if "--no-save" in line)
    stamp = next(i for i, line in enumerate(lines) if "install-stamp" in line)
    # order matters: committed layer, then overlay, then stamp freshened so
    # the webpack startup hook doesn't re-run a plain install that could
    # prune the overlay
    assert committed < overlay < stamp
    assert "leaflet@^1.9.0" in lines[overlay]


def test_npm_script_without_overlay_still_stamps() -> None:
    script = _build_npm_script([])
    assert "--no-save" not in script
    assert "install-stamp" in script
