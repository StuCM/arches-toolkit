"""Tests for ``arches-toolkit deploy``.

Direct-mode plumbing is exercised via ``--dry-run`` (no helm, no cluster);
pure helpers are tested directly. The full chart render is covered by the
chart-lint workflow, which runs the same profiles helm-side.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
import yaml

from arches_toolkit.commands import deploy as deploy_mod
from arches_toolkit.commands.deploy import (
    _deep_merge,
    _load_environments,
    _load_or_create_secrets,
    _read_env_file,
    deploy,
)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    (tmp_path / ".env").write_text(
        "PROJECT_NAME=myproj\n"
        "PROJECT_PACKAGE=myproj\n"
        "PROJECT_IMAGE=ghcr.io/example/arches-myproj\n"
        "PROJECT_TAG=main-7\n",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text("", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def test_read_env_file(project: Path) -> None:
    values = _read_env_file(project / ".env")
    assert values["PROJECT_NAME"] == "myproj"
    assert values["PROJECT_TAG"] == "main-7"


def test_deep_merge_nested_overlay() -> None:
    base = {"a": {"x": 1, "y": 2}, "b": 1}
    overlay = {"a": {"y": 3}, "c": 4}
    merged = _deep_merge(base, overlay)
    assert merged == {"a": {"x": 1, "y": 3}, "b": 1, "c": 4}
    assert base["a"]["y"] == 2  # no mutation


def test_builtin_environments_without_config(tmp_path: Path) -> None:
    envs = _load_environments(tmp_path)
    assert envs["dev"]["mode"] == "direct"
    assert envs["dev"]["devServices"] is True
    assert envs["staging"]["mode"] == "gitops"
    assert envs["prod"]["mode"] == "gitops"


def test_deploy_yaml_overlays_and_adds_environments(tmp_path: Path) -> None:
    (tmp_path / "deploy.yaml").write_text(
        yaml.safe_dump(
            {
                "environments": {
                    "dev": {"namespace": "custom-ns"},
                    "review": {"mode": "direct", "devServices": True},
                }
            }
        ),
        encoding="utf-8",
    )
    envs = _load_environments(tmp_path)
    assert envs["dev"]["namespace"] == "custom-ns"
    assert envs["dev"]["mode"] == "direct"  # built-in key survives overlay
    assert envs["review"]["mode"] == "direct"


def test_secrets_generated_once_and_gitignored(project: Path) -> None:
    first = _load_or_create_secrets(project, "dev")
    second = _load_or_create_secrets(project, "dev")
    assert first == second
    assert (project / ".deploy-secrets.dev.yaml").exists()
    assert ".deploy-secrets.*.yaml" in (project / ".gitignore").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Command behaviour (dry-run — no helm required)
# --------------------------------------------------------------------------- #


def test_dry_run_installs_services_then_app(project: Path, capsys: pytest.CaptureFixture) -> None:
    deploy(
        environment="dev",
        project_root=project,
        namespace="",
        context="",
        image_repository="",
        tag="",
        force=False,
        dry_run=True,
        render=False,
    )
    out = capsys.readouterr().out
    services_pos = out.find("upgrade --install myproj-services")
    app_pos = out.find("upgrade --install myproj ")
    assert services_pos != -1 and app_pos != -1
    assert services_pos < app_pos  # backing services first
    assert "--namespace myproj-dev" in out
    assert "values-dev.yaml" in out


def test_gitops_environment_exits_with_guidance(project: Path, capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(typer.Exit) as excinfo:
        deploy(
            environment="staging",
            project_root=project,
            namespace="",
            context="",
            image_repository="",
            tag="",
            force=False,
            dry_run=True,
            render=False,
        )
    assert excinfo.value.exit_code == 2
    assert "GitOps" in capsys.readouterr().out


def test_prod_refuses_direct_mode(project: Path) -> None:
    (project / "deploy.yaml").write_text(
        yaml.safe_dump({"environments": {"prod": {"mode": "direct"}}}),
        encoding="utf-8",
    )
    with pytest.raises(typer.BadParameter, match="gitops"):
        deploy(
            environment="prod",
            project_root=project,
            namespace="",
            context="",
            image_repository="",
            tag="",
            force=False,
            dry_run=True,
            render=False,
        )


def test_missing_image_is_an_error(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PROJECT_NAME=bare\n", encoding="utf-8")
    with pytest.raises(typer.BadParameter, match="no image"):
        deploy(
            environment="dev",
            project_root=tmp_path,
            namespace="",
            context="",
            image_repository="",
            tag="",
            force=False,
            dry_run=True,
            render=False,
        )


def test_requires_project_env(tmp_path: Path) -> None:
    with pytest.raises(typer.BadParameter, match="PROJECT_NAME"):
        deploy(
            environment="dev",
            project_root=tmp_path,
            namespace="",
            context="",
            image_repository="",
            tag="",
            force=False,
            dry_run=True,
            render=False,
        )
