"""Tests for the clone helpers and the ``switch-mode`` command."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import typer
import yaml

from arches_toolkit import apps_manifest as manifest_mod
from arches_toolkit._clone import (
    check_clone_safety,
    clone_path,
    ensure_clone,
)
from arches_toolkit.apps_manifest import AppEntry
from arches_toolkit.commands.add_app import Mode as AddMode
from arches_toolkit.commands.add_app import Source, add_app
from arches_toolkit.commands.switch_mode import Mode, switch_mode


# --------------------------------------------------------------------------- #
# git fixtures
# --------------------------------------------------------------------------- #


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def _make_remote(path: Path, *, branch: str = "main") -> Path:
    """Create a tiny git repo at ``path`` with one commit on ``branch``."""
    path.mkdir(parents=True)
    _git("init", "--initial-branch", branch, cwd=path)
    _git("config", "user.email", "t@t.t", cwd=path)
    _git("config", "user.name", "t", cwd=path)
    (path / "README").write_text("hi\n")
    _git("add", "README", cwd=path)
    _git("commit", "-m", "init", cwd=path)
    return path


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Returns (project_root, remote_path). project_root is fresh and empty
    apart from apps.yaml; remote is a usable git repo."""
    project = tmp_path / "workspace" / "project"
    project.mkdir(parents=True)
    remote = _make_remote(tmp_path / "remote-arches-her")
    return project, remote


# --------------------------------------------------------------------------- #
# ensure_clone
# --------------------------------------------------------------------------- #


def test_ensure_clone_creates_sibling_dir(workspace) -> None:
    project, remote = workspace
    entry = AppEntry(package="arches-her", source="git", repo=str(remote), mode="develop")
    path, action = ensure_clone(entry, project)
    assert action == "cloned"
    assert path == project.resolve().parent / "remote-arches-her"
    assert (path / ".git").exists()
    assert (path / "README").read_text() == "hi\n"


def test_ensure_clone_is_idempotent(workspace) -> None:
    project, remote = workspace
    entry = AppEntry(package="arches-her", source="git", repo=str(remote), mode="develop")
    ensure_clone(entry, project)
    path, action = ensure_clone(entry, project)
    assert action == "exists"


def test_ensure_clone_requires_repo(workspace) -> None:
    project, _ = workspace
    entry = AppEntry(package="arches-her", source="pypi", mode="develop")
    with pytest.raises(typer.BadParameter):
        ensure_clone(entry, project)


def test_ensure_clone_uses_path_override(workspace) -> None:
    project, remote = workspace
    entry = AppEntry(
        package="arches-her", source="git", repo=str(remote),
        mode="develop", path="2.0.x",
    )
    path, action = ensure_clone(entry, project)
    assert action == "cloned"
    assert path == project.resolve().parent / "2.0.x"


# --------------------------------------------------------------------------- #
# check_clone_safety
# --------------------------------------------------------------------------- #


def test_safety_clean_clone_with_upstream(workspace) -> None:
    project, remote = workspace
    entry = AppEntry(package="arches-her", source="git", repo=str(remote), mode="develop")
    ensure_clone(entry, project)
    # clone has remote 'origin' tracking, no local commits beyond it
    assert check_clone_safety(entry, project) == []


def test_safety_missing_clone_is_safe(workspace) -> None:
    project, _ = workspace
    entry = AppEntry(package="arches-her", source="git", repo="x", mode="develop")
    # no clone exists; nothing to lose
    assert check_clone_safety(entry, project) == []


def test_safety_uncommitted_changes_flagged(workspace) -> None:
    project, remote = workspace
    entry = AppEntry(package="arches-her", source="git", repo=str(remote), mode="develop")
    path, _ = ensure_clone(entry, project)
    (path / "new.txt").write_text("dirty\n")
    issues = check_clone_safety(entry, project)
    assert any("uncommitted" in i for i in issues)


def test_safety_unpushed_commits_flagged(workspace) -> None:
    project, remote = workspace
    entry = AppEntry(package="arches-her", source="git", repo=str(remote), mode="develop")
    path, _ = ensure_clone(entry, project)
    _git("config", "user.email", "t@t.t", cwd=path)
    _git("config", "user.name", "t", cwd=path)
    (path / "x").write_text("x")
    _git("add", "x", cwd=path)
    _git("commit", "-m", "local", cwd=path)
    issues = check_clone_safety(entry, project)
    assert any("unpushed" in i for i in issues)


# --------------------------------------------------------------------------- #
# switch_mode
# --------------------------------------------------------------------------- #


def _write_manifest(project: Path, entries: list[dict]) -> Path:
    p = project / "apps.yaml"
    p.write_text(yaml.safe_dump({"apps": entries}, sort_keys=False))
    return p


def test_switch_release_to_develop_clones_and_flips(workspace) -> None:
    project, remote = workspace
    manifest = _write_manifest(project, [
        {"package": "arches-her", "source": "git", "repo": str(remote), "mode": "release"},
    ])
    switch_mode(
        package="arches-her", target=Mode.develop,
        repo=None, force=False, no_sync=True,
        manifest_path=manifest, project_root=project,
    )
    saved = manifest_mod.load(manifest).find("arches-her")
    assert saved.mode == "develop"
    assert (clone_path(saved, project) / ".git").exists()


def test_switch_pypi_to_develop_requires_repo(workspace) -> None:
    project, _ = workspace
    manifest = _write_manifest(project, [
        {"package": "arches-her", "source": "pypi", "version": "~=2.0", "mode": "release"},
    ])
    with pytest.raises(typer.BadParameter):
        switch_mode(
            package="arches-her", target=Mode.develop,
            repo=None, force=False, no_sync=True,
            manifest_path=manifest, project_root=project,
        )


def test_switch_pypi_to_develop_persists_repo(workspace) -> None:
    project, remote = workspace
    manifest = _write_manifest(project, [
        {"package": "arches-her", "source": "pypi", "version": "~=2.0", "mode": "release"},
    ])
    switch_mode(
        package="arches-her", target=Mode.develop,
        repo=str(remote), force=False, no_sync=True,
        manifest_path=manifest, project_root=project,
    )
    saved = manifest_mod.load(manifest).find("arches-her")
    assert saved.mode == "develop"
    assert saved.repo == str(remote)
    # source stays pypi — install spec isn't tied to clone
    assert saved.source == "pypi"


def test_switch_develop_to_release_clean(workspace) -> None:
    project, remote = workspace
    manifest = _write_manifest(project, [
        {"package": "arches-her", "source": "git", "repo": str(remote), "mode": "develop"},
    ])
    # pre-create the clone so it's clean+pushed
    ensure_clone(AppEntry(package="arches-her", repo=str(remote)), project)
    switch_mode(
        package="arches-her", target=Mode.release,
        repo=None, force=False, no_sync=True,
        manifest_path=manifest, project_root=project,
    )
    saved = manifest_mod.load(manifest).find("arches-her")
    assert saved.mode == "release"
    # clone preserved
    assert (project.resolve().parent / "remote-arches-her").exists()


def test_switch_develop_to_release_refuses_dirty(workspace) -> None:
    project, remote = workspace
    manifest = _write_manifest(project, [
        {"package": "arches-her", "source": "git", "repo": str(remote), "mode": "develop"},
    ])
    path, _ = ensure_clone(
        AppEntry(package="arches-her", repo=str(remote)), project
    )
    (path / "dirty").write_text("x")
    with pytest.raises(typer.BadParameter, match="uncommitted"):
        switch_mode(
            package="arches-her", target=Mode.release,
            repo=None, force=False, no_sync=True,
            manifest_path=manifest, project_root=project,
        )
    # mode unchanged because we refused
    assert manifest_mod.load(manifest).find("arches-her").mode == "develop"


def test_switch_develop_to_release_force_overrides(workspace) -> None:
    project, remote = workspace
    manifest = _write_manifest(project, [
        {"package": "arches-her", "source": "git", "repo": str(remote), "mode": "develop"},
    ])
    path, _ = ensure_clone(
        AppEntry(package="arches-her", repo=str(remote)), project
    )
    (path / "dirty").write_text("x")
    switch_mode(
        package="arches-her", target=Mode.release,
        repo=None, force=True, no_sync=True,
        manifest_path=manifest, project_root=project,
    )
    assert manifest_mod.load(manifest).find("arches-her").mode == "release"
    # dirty file is still there — clone untouched
    assert (path / "dirty").exists()


def test_switch_does_not_touch_clone_branch(workspace) -> None:
    """ref in apps.yaml is decoupled from the clone's actual HEAD."""
    project, remote = workspace
    manifest = _write_manifest(project, [
        {"package": "arches-her", "source": "git", "repo": str(remote),
         "ref": "main", "mode": "release"},
    ])
    switch_mode(
        package="arches-her", target=Mode.develop,
        repo=None, force=False, no_sync=True,
        manifest_path=manifest, project_root=project,
    )
    path = clone_path(
        manifest_mod.load(manifest).find("arches-her"), project
    )
    # check out a new branch in the clone
    _git("checkout", "-b", "user-feature", cwd=path)
    # flip back to release; ref in apps.yaml should still be 'main'.
    # The new branch has no upstream so we --force past the safety gate —
    # the gate working correctly here is the subject of a different test.
    switch_mode(
        package="arches-her", target=Mode.release,
        repo=None, force=True, no_sync=True,
        manifest_path=manifest, project_root=project,
    )
    saved = manifest_mod.load(manifest).find("arches-her")
    assert saved.ref == "main"
    # and the clone still has the user's branch
    head = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=path, capture_output=True, text=True,
    )
    assert head.stdout.strip() == "user-feature"


def test_switch_rolls_back_manifest_on_install_failure(workspace, monkeypatch) -> None:
    """A failed install (network down, broken dep) must not leave apps.yaml
    claiming a mode the stack was never converged to."""
    from arches_toolkit.commands import switch_mode as sm

    project, remote = workspace
    manifest = _write_manifest(project, [
        {"package": "arches-her", "source": "git", "repo": str(remote), "mode": "develop"},
    ])
    ensure_clone(AppEntry(package="arches-her", repo=str(remote)), project)

    monkeypatch.setattr(sm.sync_apps_cmd, "sync_apps", lambda **kw: None)

    def boom(**kw):
        raise typer.Exit(1)

    monkeypatch.setattr(sm.install_cmd, "install", boom)

    with pytest.raises(typer.Exit):
        switch_mode(
            package="arches-her", target=Mode.release,
            repo=None, force=False, no_sync=False, no_install=False,
            manifest_path=manifest, project_root=project,
        )
    saved = manifest_mod.load(manifest).find("arches-her")
    assert saved.mode == "develop"


def test_switch_rolls_back_repo_too_on_failure(workspace, monkeypatch) -> None:
    """Rollback restores the whole prior entry — a --repo persisted during a
    failed develop switch doesn't survive."""
    from arches_toolkit.commands import switch_mode as sm

    project, remote = workspace
    manifest = _write_manifest(project, [
        {"package": "arches-her", "source": "pypi", "version": "~=2.0", "mode": "release"},
    ])

    monkeypatch.setattr(sm.sync_apps_cmd, "sync_apps", lambda **kw: None)

    def boom(**kw):
        raise typer.Exit(1)

    monkeypatch.setattr(sm.install_cmd, "install", boom)

    with pytest.raises(typer.Exit):
        switch_mode(
            package="arches-her", target=Mode.develop,
            repo=str(remote), force=False, no_sync=False, no_install=False,
            manifest_path=manifest, project_root=project,
        )
    saved = manifest_mod.load(manifest).find("arches-her")
    assert saved.mode == "release"
    assert saved.repo is None


def test_switch_unknown_package_errors(workspace) -> None:
    project, _ = workspace
    manifest = _write_manifest(project, [])
    with pytest.raises(typer.BadParameter, match="not found"):
        switch_mode(
            package="nope", target=Mode.develop,
            repo=None, force=False, no_sync=True,
            manifest_path=manifest, project_root=project,
        )


def test_switch_release_to_release_is_noop(workspace) -> None:
    project, remote = workspace
    manifest = _write_manifest(project, [
        {"package": "arches-her", "source": "git", "repo": str(remote), "mode": "release"},
    ])
    switch_mode(
        package="arches-her", target=Mode.release,
        repo=None, force=False, no_sync=True,
        manifest_path=manifest, project_root=project,
    )
    # nothing cloned, mode unchanged
    assert manifest_mod.load(manifest).find("arches-her").mode == "release"
    assert not (project.resolve().parent / "remote-arches-her").exists()


# --------------------------------------------------------------------------- #
# add_app validation + clone hand-off
# --------------------------------------------------------------------------- #


def test_add_app_pypi_with_repo_release_rejected(workspace) -> None:
    project, remote = workspace
    manifest = project / "apps.yaml"
    with pytest.raises(typer.BadParameter, match="develop mode"):
        add_app(
            package="arches-her", source=Source.pypi, version="~=2.0",
            repo=str(remote), ref=None, mode=AddMode.release,
            manifest_path=manifest,
        )


def test_add_app_develop_pypi_without_repo_rejected(workspace) -> None:
    project, _ = workspace
    manifest = project / "apps.yaml"
    with pytest.raises(typer.BadParameter, match="--repo URL is required"):
        add_app(
            package="arches-her", source=Source.pypi, version="~=2.0",
            repo=None, ref=None, mode=AddMode.develop,
            manifest_path=manifest,
        )


def test_add_app_develop_pypi_with_repo_clones(workspace) -> None:
    project, remote = workspace
    manifest = project / "apps.yaml"
    add_app(
        package="arches-her", source=Source.pypi, version="~=2.0",
        repo=str(remote), ref=None, mode=AddMode.develop,
        manifest_path=manifest,
    )
    saved = manifest_mod.load(manifest).find("arches-her")
    assert saved.mode == "develop"
    assert saved.source == "pypi"
    assert saved.repo == str(remote)
    assert (project.resolve().parent / "remote-arches-her" / ".git").exists()


def test_add_app_develop_git_clones(workspace) -> None:
    project, remote = workspace
    manifest = project / "apps.yaml"
    add_app(
        package="arches-her", source=Source.git, version=None,
        repo=str(remote), ref=None, mode=AddMode.develop,
        manifest_path=manifest,
    )
    assert (project.resolve().parent / "remote-arches-her" / ".git").exists()
