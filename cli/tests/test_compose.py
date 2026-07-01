"""Tests for the shared compose helpers (_compose) and the generic
``arches-toolkit compose`` command. These do not start Docker.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from arches_toolkit import _compose
from arches_toolkit import main as main_module
from arches_toolkit.commands import compose_wrappers


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Don't let the host's COMPOSE_PROJECT_NAME / ARCHES_SRC leak into tests."""
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)
    monkeypatch.delenv("ARCHES_SRC", raising=False)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text("PROJECT_NAME=test\n", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# normalize_project_name
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("myproject", "myproject"),
        ("My-Project", "my-project"),
        ("arches_quartz", "arches_quartz"),
        ("Catalina 8.1", "catalina81"),
        ("--weird--", "weird--"),
        ("", "arches"),
        ("...", "arches"),
    ],
)
def test_normalize_project_name(raw, expected):
    assert _compose.normalize_project_name(raw) == expected


# --------------------------------------------------------------------------- #
# project_name / ensure_project_name
# --------------------------------------------------------------------------- #

def test_project_name_explicit_from_env_file(tmp_path: Path):
    (tmp_path / ".env").write_text("COMPOSE_PROJECT_NAME=explicit_name\n", encoding="utf-8")
    assert _compose.project_name(tmp_path) == "explicit_name"


def test_project_name_explicit_from_shell_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "shell_name")
    assert _compose.project_name(tmp_path) == "shell_name"


def test_project_name_derived_from_dir_basename(tmp_path: Path):
    proj = tmp_path / "MyProj"
    proj.mkdir()
    assert _compose.project_name(proj) == "myproj"


def test_ensure_project_name_appends_when_missing(project_dir: Path):
    name = _compose.ensure_project_name(project_dir)
    text = (project_dir / ".env").read_text(encoding="utf-8")
    assert f"COMPOSE_PROJECT_NAME={name}" in text
    # Idempotent: a second call doesn't duplicate the line.
    _compose.ensure_project_name(project_dir)
    assert text.count("COMPOSE_PROJECT_NAME=") == 1
    assert (project_dir / ".env").read_text().count("COMPOSE_PROJECT_NAME=") == 1


def test_ensure_project_name_noop_when_present(tmp_path: Path):
    (tmp_path / ".env").write_text("COMPOSE_PROJECT_NAME=already\n", encoding="utf-8")
    assert _compose.ensure_project_name(tmp_path) == "already"
    assert (tmp_path / ".env").read_text().count("COMPOSE_PROJECT_NAME=") == 1


def test_ensure_project_name_no_env_file_does_not_write(tmp_path: Path):
    proj = tmp_path / "noenv"
    proj.mkdir()
    name = _compose.ensure_project_name(proj)
    assert name == "noenv"
    assert not (proj / ".env").exists()


# --------------------------------------------------------------------------- #
# compose_files — overlay inclusion
# --------------------------------------------------------------------------- #

def test_compose_files_baseline_only(project_dir: Path):
    names = [p.name for p in _compose.compose_files(project_dir)]
    assert names == ["compose.yaml", "compose.dev.yaml"]


def test_compose_files_includes_extras(project_dir: Path):
    (project_dir / "compose.extras.yaml").write_text("services: {}\n", encoding="utf-8")
    names = [p.name for p in _compose.compose_files(project_dir)]
    assert "compose.extras.yaml" in names


def test_compose_files_includes_arches_src_overlay_when_set(project_dir, monkeypatch):
    monkeypatch.setenv("ARCHES_SRC", "/opt/arches-clone")
    names = [p.name for p in _compose.compose_files(project_dir)]
    assert "compose.arches-src.yaml" in names


# --------------------------------------------------------------------------- #
# `arches-toolkit compose <args>` command
# --------------------------------------------------------------------------- #

def test_compose_command_builds_argv_and_persists_name(
    runner: CliRunner, project_dir: Path, monkeypatch
):
    captured = {}

    def fake_run(argv, env=None, **kwargs):
        captured["argv"] = argv
        captured["env"] = env

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(compose_wrappers.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(compose_wrappers.subprocess, "run", fake_run)

    result = runner.invoke(
        main_module.app,
        ["compose", "--project-root", str(project_dir), "config", "--services"],
    )
    assert result.exit_code == 0, result.output
    argv = captured["argv"]
    assert argv[:2] == ["docker", "compose"]
    assert "--project-directory" in argv
    assert argv[-2:] == ["config", "--services"]
    # canonical packaged stack is present
    assert any(a.endswith("compose.yaml") for a in argv)
    assert any(a.endswith("compose.dev.yaml") for a in argv)
    # the Dockerfile interpolation var is exported
    assert "ARCHES_TOOLKIT_DOCKERFILE" in captured["env"]
    # and the project name was self-healed into .env
    assert "COMPOSE_PROJECT_NAME=" in (project_dir / ".env").read_text(encoding="utf-8")


def test_compose_command_requires_env(runner: CliRunner, tmp_path: Path):
    result = runner.invoke(
        main_module.app, ["compose", "--project-root", str(tmp_path), "ps"]
    )
    assert result.exit_code != 0
    assert "no .env found" in result.output
