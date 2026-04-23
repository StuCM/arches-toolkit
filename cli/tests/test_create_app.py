"""Tests for ``arches-toolkit create app`` — specifically how it auto-registers
the new app into apps.yaml.
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
    """A project-root-like dir with an (empty) apps.yaml.

    create app registers when cwd has apps.yaml. Use --project-root to point
    sync-apps etc. at this dir; create app itself reads `Path.cwd()` so its
    tests need to run *inside* this dir.
    """
    (tmp_path / "apps.yaml").write_text("apps: []\n", encoding="utf-8")
    return tmp_path


def test_create_app_auto_registers_as_pypi_placeholder(
    runner: CliRunner, project_dir: Path, monkeypatch, tmp_path: Path
):
    """Newly scaffolded apps auto-register in apps.yaml with source: pypi as
    a placeholder, mode: develop. The user must then either push the clone
    to git and flip source → git, OR hand-edit pyproject with a file://
    URL, before running sync-apps. See TASKS.md "Open design problem:
    scaffolded local-only apps" for why we can't do better yet."""
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
    entries = apps_yaml["apps"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["package"] == "arches-my-new-thing"
    assert entry["source"] == "pypi"
    assert entry["mode"] == "develop"
    # Output should nudge the user to flip to a real source
    assert "push the scaffold to git" in result.output or "push to git" in result.output


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
