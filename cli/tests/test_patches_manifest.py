"""Tests for the patch control plane (patches_manifest) and the
`patch list/enable/disable` CLI. No git or Docker required."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from arches_toolkit import patches as patches_mod
from arches_toolkit import patches_manifest as pm
from arches_toolkit import main as main_module


def _write_patch(directory: Path, stem: str, subject: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / f"{stem}.patch"
    p.write_text(
        "From 0000000 Mon Sep 17 00:00:00 2001\n"
        "From: Test <t@example.com>\n"
        f"Subject: [PATCH] {subject}\n\n"
        "Body line.\n\n"
        "Upstream: none yet\n"
        "Last-reviewed: 2026-01-01\n"
        "Reason: testing\n"
        "---\n"
        " a.txt | 1 +\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def toolkit_dir(tmp_path: Path) -> Path:
    d = tmp_path / "shipped"
    _write_patch(d, "0001-frontend-config", "honour env var")
    _write_patch(d, "0002-some-fix", "fix a thing")
    return d


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return tmp_path / "proj"


# --------------------------------------------------------------------------- #
# load / enabled
# --------------------------------------------------------------------------- #

def test_load_toolkit_and_local(toolkit_dir, project):
    _write_patch(pm.local_patches_dir(project), "my-local-fix", "local thing")
    entries = pm.load(project, toolkit_dir=toolkit_dir)
    ids = [(e.id, e.source, e.enabled) for e in entries]
    assert ids == [
        ("0001-frontend-config", "toolkit", True),
        ("0002-some-fix", "toolkit", True),
        ("my-local-fix", "local", True),
    ]


def test_everything_enabled_by_default_no_manifest(toolkit_dir, project):
    assert not pm.manifest_path(project).exists()
    assert len(pm.enabled_patches(project, toolkit_dir=toolkit_dir)) == 2


def test_disable_then_enable_roundtrip(toolkit_dir, project):
    pm.set_enabled(project, ["0002-some-fix"], enabled=False, toolkit_dir=toolkit_dir)
    enabled = [e.id for e in pm.enabled_patches(project, toolkit_dir=toolkit_dir)]
    assert enabled == ["0001-frontend-config"]
    assert pm.manifest_path(project).exists()
    assert "0002-some-fix" in pm.manifest_path(project).read_text()

    # enabling the last disabled patch removes the now-empty manifest
    pm.set_enabled(project, ["0002-some-fix"], enabled=True, toolkit_dir=toolkit_dir)
    assert len(pm.enabled_patches(project, toolkit_dir=toolkit_dir)) == 2
    assert not pm.manifest_path(project).exists()


# --------------------------------------------------------------------------- #
# selector resolution
# --------------------------------------------------------------------------- #

def test_resolve_by_full_id(toolkit_dir, project):
    entries = pm.load(project, toolkit_dir=toolkit_dir)
    assert pm.resolve(entries, "0001-frontend-config").id == "0001-frontend-config"


def test_resolve_by_number(toolkit_dir, project):
    entries = pm.load(project, toolkit_dir=toolkit_dir)
    assert pm.resolve(entries, "2").id == "0002-some-fix"
    assert pm.resolve(entries, "0001").id == "0001-frontend-config"


def test_resolve_by_unique_substring(toolkit_dir, project):
    entries = pm.load(project, toolkit_dir=toolkit_dir)
    assert pm.resolve(entries, "frontend").id == "0001-frontend-config"


def test_resolve_ambiguous_raises(toolkit_dir, project):
    # both share the substring "fix"? no — "some-fix" and a local "fix"
    _write_patch(pm.local_patches_dir(project), "another-fix", "x")
    entries = pm.load(project, toolkit_dir=toolkit_dir)
    with pytest.raises(pm.PatchSelectorError):
        pm.resolve(entries, "fix")


def test_resolve_none_raises(toolkit_dir, project):
    entries = pm.load(project, toolkit_dir=toolkit_dir)
    with pytest.raises(pm.PatchSelectorError):
        pm.resolve(entries, "nope")


def test_set_enabled_bad_selector_writes_nothing(toolkit_dir, project):
    with pytest.raises(pm.PatchSelectorError):
        pm.set_enabled(project, ["nope"], enabled=False, toolkit_dir=toolkit_dir)
    assert not pm.manifest_path(project).exists()


def test_stale_disabled_ids_pruned_on_write(toolkit_dir, project):
    pm.manifest_path(project).parent.mkdir(parents=True, exist_ok=True)
    pm.manifest_path(project).write_text("disabled:\n  - ghost-patch\n  - 0002-some-fix\n")
    # toggling something prunes the unknown id
    pm.set_enabled(project, ["0001-frontend-config"], enabled=False, toolkit_dir=toolkit_dir)
    text = pm.manifest_path(project).read_text()
    assert "ghost-patch" not in text
    assert "0001-frontend-config" in text
    assert "0002-some-fix" in text


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_cli_list_and_toggle(runner, toolkit_dir, project, monkeypatch):
    monkeypatch.setattr(patches_mod, "shipped_patches_dir", lambda: toolkit_dir)
    monkeypatch.setenv("COLUMNS", "200")  # stop rich from folding the id column
    project.mkdir(parents=True, exist_ok=True)

    r = runner.invoke(main_module.app, ["patch", "list", "--project-root", str(project)])
    assert r.exit_code == 0, r.output
    assert "0001-frontend-config" in r.output
    assert "0002-some-fix" in r.output

    r = runner.invoke(
        main_module.app, ["patch", "disable", "2", "--project-root", str(project)]
    )
    assert r.exit_code == 0, r.output
    assert "disabled: 0002-some-fix" in r.output
    assert "0002-some-fix" in pm.manifest_path(project).read_text()

    r = runner.invoke(
        main_module.app, ["patch", "enable", "0002", "--project-root", str(project)]
    )
    assert r.exit_code == 0, r.output
    assert "enabled: 0002-some-fix" in r.output


def test_cli_disable_bad_selector_errors(runner, toolkit_dir, project, monkeypatch):
    monkeypatch.setattr(patches_mod, "shipped_patches_dir", lambda: toolkit_dir)
    project.mkdir(parents=True, exist_ok=True)
    r = runner.invoke(
        main_module.app, ["patch", "disable", "ghost", "--project-root", str(project)]
    )
    assert r.exit_code == 1
    assert "matches no patch" in r.output


# --------------------------------------------------------------------------- #
# add / rm / promote
# --------------------------------------------------------------------------- #

def test_add_local_registers_patch(tmp_path, toolkit_dir, project):
    src = _write_patch(tmp_path / "incoming", "my-fix", "a local fix")
    e = pm.add_local(project, src)
    assert e.id == "my-fix" and e.source == "local" and e.enabled
    ids = [x.id for x in pm.load(project, toolkit_dir=toolkit_dir)]
    assert "my-fix" in ids
    assert (pm.local_patches_dir(project) / "my-fix.patch").exists()


def test_add_local_clash_without_force(tmp_path, project):
    src = _write_patch(tmp_path / "incoming", "dupe", "x")
    pm.add_local(project, src)
    with pytest.raises(pm.PatchError):
        pm.add_local(project, src)
    pm.add_local(project, src, force=True)  # force overwrites


def test_add_local_missing_source(project):
    with pytest.raises(pm.PatchError):
        pm.add_local(project, project / "nope.patch")


def test_remove_local_deletes_file(tmp_path, project):
    src = _write_patch(tmp_path / "incoming", "kill-me", "x")
    pm.add_local(project, src)
    assert (pm.local_patches_dir(project) / "kill-me.patch").exists()
    pm.remove_local(project, "kill-me")
    assert not (pm.local_patches_dir(project) / "kill-me.patch").exists()


def test_remove_local_refuses_toolkit_patch(toolkit_dir, project):
    with pytest.raises(pm.PatchError):
        pm.remove_local(project, "0001-frontend-config")


def test_remove_local_prunes_disabled(tmp_path, toolkit_dir, project):
    src = _write_patch(tmp_path / "incoming", "temp", "x")
    pm.add_local(project, src)
    pm.set_enabled(project, ["temp"], enabled=False, toolkit_dir=toolkit_dir)
    pm.remove_local(project, "temp")
    # the now-gone id should not linger in patches.yaml
    if pm.manifest_path(project).exists():
        assert "temp" not in pm.manifest_path(project).read_text()


def test_promote_local_to_toolkit(tmp_path, project, monkeypatch):
    shipped = tmp_path / "shipped"
    _write_patch(shipped, "0001-existing", "existing")
    monkeypatch.setattr(patches_mod, "shipped_patches_dir", lambda: shipped)

    src = _write_patch(tmp_path / "incoming", "great-fix", "great fix")
    pm.add_local(project, src)
    dest, new_id = pm.promote(project, "great-fix", upstream="none yet", reason="useful")

    assert dest.parent == shipped
    assert new_id == "0002-great-fix"  # next number after 0001
    assert dest.exists()
    assert not (pm.local_patches_dir(project) / "great-fix.patch").exists()
    # headers were injected
    assert "Reason: useful" in dest.read_text()


def test_promote_refuses_toolkit_patch(tmp_path, project, monkeypatch):
    shipped = tmp_path / "shipped"
    _write_patch(shipped, "0001-already", "x")
    monkeypatch.setattr(patches_mod, "shipped_patches_dir", lambda: shipped)
    with pytest.raises(pm.PatchError):
        pm.promote(project, "0001-already")


def test_promote_refuses_site_packages(project, monkeypatch):
    monkeypatch.setattr(
        patches_mod, "shipped_patches_dir",
        lambda: Path("/usr/lib/python3/site-packages/arches_toolkit/_data/patches"),
    )
    with pytest.raises(pm.PatchError):
        pm.promote(project, "anything")


def test_cli_add_rm(runner, tmp_path, toolkit_dir, project, monkeypatch):
    monkeypatch.setattr(patches_mod, "shipped_patches_dir", lambda: toolkit_dir)
    project.mkdir(parents=True, exist_ok=True)
    src = _write_patch(tmp_path / "incoming", "cli-fix", "via cli")

    r = runner.invoke(
        main_module.app, ["patch", "add", str(src), "--project-root", str(project)]
    )
    assert r.exit_code == 0, r.output
    assert "added local patch: cli-fix" in r.output

    r = runner.invoke(
        main_module.app, ["patch", "rm", "cli-fix", "--project-root", str(project)]
    )
    assert r.exit_code == 0, r.output
    assert "removed local patch: cli-fix" in r.output
