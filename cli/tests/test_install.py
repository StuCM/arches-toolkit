"""Tests for the install-script construction. The actual `install` command
shells out to `docker compose` and isn't unit-tested here — that's covered
by manual smoke testing against a real project."""

from __future__ import annotations

from arches_toolkit.apps_manifest import AppEntry
from arches_toolkit.commands.install import _build_install_script


def test_install_script_no_develop_apps() -> None:
    script = _build_install_script([])
    lines = script.splitlines()
    assert lines[0] == "set -eux"
    assert any("uv pip install" in l and "-e ." in l for l in lines)
    assert "/workspace" not in script


def test_install_script_includes_prerelease_allow() -> None:
    """The whole flow assumes pre-releases are OK — bake it in."""
    script = _build_install_script([])
    assert "--prerelease=allow" in script


def test_install_script_one_line_per_develop_app() -> None:
    script = _build_install_script([
        AppEntry(package="arches-her", source="git",
                 repo="https://github.com/x/arches-her.git", mode="develop"),
        AppEntry(package="arches-foo", source="git",
                 repo="https://github.com/x/arches-foo.git", mode="develop"),
    ])
    assert "-e /workspace/arches-her" in script
    assert "-e /workspace/arches-foo" in script


def test_install_script_uses_path_override_for_clone_dir() -> None:
    """Develop entries with explicit `path:` install from /workspace/<path>,
    matching the sibling-dir convention shared with switch-mode/clone."""
    script = _build_install_script([
        AppEntry(package="arches-her", source="git",
                 repo="https://github.com/x/arches-her.git",
                 mode="develop", path="2.0.x"),
    ])
    assert "-e /workspace/2.0.x" in script
    # And not the package-derived dir name
    assert "-e /workspace/arches-her" not in script
