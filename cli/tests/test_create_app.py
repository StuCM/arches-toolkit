"""Tests for ``arches-toolkit create app`` — scaffold location, git init, and
the deliberate absence of apps.yaml auto-registration (apps register via
``add-app --repo`` once pushed; everything in apps.yaml must be installable
by any teammate).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from arches_toolkit import main as main_module


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A project-root-like dir (workspace/project) with an (empty) apps.yaml.

    create app reads `Path.cwd()` so its tests need to run *inside* this dir.
    """
    project = tmp_path / "workspace" / "project"
    project.mkdir(parents=True)
    (project / "apps.yaml").write_text("apps: []\n", encoding="utf-8")
    return project


def test_create_app_does_not_register(
    runner: CliRunner, project_dir: Path, monkeypatch, tmp_path: Path
):
    """Scaffolds are NOT auto-registered: apps.yaml entries must be installable
    by any teammate (uv lock resolves develop entries as git+repo@ref), and a
    fresh scaffold has no pushed repo yet. The output points at the push +
    add-app flow instead."""
    monkeypatch.chdir(project_dir)
    scaffold_parent = tmp_path / "scaffolds"
    scaffold_parent.mkdir()

    result = runner.invoke(
        main_module.app,
        [
            "create", "app", "my_new_thing",
            "--path", str(scaffold_parent),
            "--arches-version", "8.1",
        ],
    )
    assert result.exit_code == 0, result.output

    apps_yaml = yaml.safe_load(
        (project_dir / "apps.yaml").read_text(encoding="utf-8")
    )
    assert apps_yaml["apps"] == []
    assert "add-app arches-my-new-thing" in result.output
    assert "--repo" in result.output


def test_create_app_defaults_to_sibling_of_project(
    runner: CliRunner, project_dir: Path, monkeypatch
):
    """Run from a project root (cwd has apps.yaml) with no --path, the app
    scaffolds as a *sibling* of the project — the location the /workspace
    mount and add-app's clone convention expect."""
    monkeypatch.chdir(project_dir)

    result = runner.invoke(
        main_module.app,
        ["create", "app", "my_new_thing", "--arches-version", "8.1"],
    )
    assert result.exit_code == 0, result.output

    sibling = project_dir.parent / "arches-my-new-thing"
    assert sibling.is_dir()
    assert not (project_dir / "arches-my-new-thing").exists()


def test_create_app_defaults_to_cwd_outside_project(
    runner: CliRunner, monkeypatch, tmp_path: Path
):
    """Without apps.yaml in cwd there is no project to be a sibling of —
    scaffold into cwd as before."""
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)

    result = runner.invoke(
        main_module.app,
        ["create", "app", "my_new_thing", "--arches-version", "8.1"],
    )
    assert result.exit_code == 0, result.output
    assert (plain / "arches-my-new-thing").is_dir()


def test_create_app_git_inits_scaffold(
    runner: CliRunner, project_dir: Path, monkeypatch, tmp_path: Path
):
    """The scaffold becomes its own git repo so the user is one
    `remote add` + `push` away from a registrable app."""
    monkeypatch.chdir(project_dir)
    scaffold_parent = tmp_path / "scaffolds"
    scaffold_parent.mkdir()

    result = runner.invoke(
        main_module.app,
        [
            "create", "app", "my_new_thing",
            "--path", str(scaffold_parent),
            "--arches-version", "8.1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (scaffold_parent / "arches-my-new-thing" / ".git").is_dir()


def test_create_app_accepts_kebab_case_name(
    runner: CliRunner, project_dir: Path, monkeypatch, tmp_path: Path
):
    """Both kebab-case (`file-upload-3d`) and snake_case (`file_upload_3d`)
    are accepted — the kebab form matches PyPI dist-name conventions which
    users are likely to type."""
    monkeypatch.chdir(project_dir)
    scaffold_parent = tmp_path / "scaffolds"
    scaffold_parent.mkdir()

    result = runner.invoke(
        main_module.app,
        [
            "create", "app", "file-upload-3d",
            "--path", str(scaffold_parent),
            "--arches-version", "8.1",
        ],
    )
    assert result.exit_code == 0, result.output

    # Scaffolded dir uses kebab form; Python package inside uses underscores
    assert (scaffold_parent / "arches-file-upload-3d").is_dir()
    assert (
        scaffold_parent / "arches-file-upload-3d" / "arches_file_upload_3d"
    ).is_dir()
