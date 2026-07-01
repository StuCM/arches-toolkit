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


# --------------------------------------------------------------------------- #
# GitOps promotion
# --------------------------------------------------------------------------- #

HELMRELEASE = """\
# HelmRelease for myproj — hand-maintained; comments must survive edits.
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: myproj
spec:
  values:
    image:
      repository: ghcr.io/example/arches-myproj
      tag: main-1  # bumped by arches-toolkit deploy
---
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImagePolicy
metadata:
  name: myproj
"""


@pytest.fixture()
def fluxcd_repo(tmp_path: Path) -> Path:
    """Local bare repo standing in for the fluxcd repo."""
    import subprocess

    bare = tmp_path / "fluxcd.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(bare), str(seed)], check=True, capture_output=True)
    target = seed / "namespaces" / "myproj-staging"
    target.mkdir(parents=True)
    (target / "helmrelease.yaml").write_text(HELMRELEASE, encoding="utf-8")
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": __import__("os").environ["PATH"],
    }
    subprocess.run(["git", "add", "-A"], cwd=seed, check=True, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=seed, check=True, capture_output=True, env=env)
    subprocess.run(["git", "push", "origin", "main"], cwd=seed, check=True, capture_output=True, env=env)
    return bare


def _write_gitops_config(project: Path, bare: Path, **extra) -> None:
    (project / "deploy.yaml").write_text(
        yaml.safe_dump(
            {
                "environments": {
                    "staging": {
                        "mode": "gitops",
                        "gitops": {
                            "repo": str(bare),
                            "file": "namespaces/myproj-staging/helmrelease.yaml",
                            **extra,
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def _promoted_file(bare: Path, ref: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "show", f"{ref}:namespaces/myproj-staging/helmrelease.yaml"],
        cwd=bare, check=True, capture_output=True, text=True,
    ).stdout


def test_gitops_promotion_pushes_deploy_branch(project: Path, fluxcd_repo: Path) -> None:
    _write_gitops_config(project, fluxcd_repo)
    deploy(
        environment="staging", project_root=project, namespace="", context="",
        image_repository="", tag="main-99", force=False, dry_run=False, render=False,
    )
    content = _promoted_file(fluxcd_repo, "deploy/myproj-staging-main-99")
    assert "tag: main-99" in content
    assert "hand-maintained; comments must survive" in content
    assert "bumped by arches-toolkit deploy" in content  # inline comment kept
    assert "kind: ImagePolicy" in content  # second document intact


def test_gitops_direct_push_lands_on_base_branch(project: Path, fluxcd_repo: Path) -> None:
    _write_gitops_config(project, fluxcd_repo, push="direct")
    deploy(
        environment="staging", project_root=project, namespace="", context="",
        image_repository="", tag="main-42", force=False, dry_run=False, render=False,
    )
    assert "tag: main-42" in _promoted_file(fluxcd_repo, "main")


def test_gitops_requires_explicit_tag(project: Path, fluxcd_repo: Path) -> None:
    _write_gitops_config(project, fluxcd_repo)
    with pytest.raises(typer.BadParameter, match="--tag"):
        deploy(
            environment="staging", project_root=project, namespace="", context="",
            image_repository="", tag="", force=False, dry_run=False, render=False,
        )


def test_gitops_bad_tag_path_is_loud(project: Path, fluxcd_repo: Path) -> None:
    _write_gitops_config(project, fluxcd_repo, tagPath="spec.values.nope.tag")
    with pytest.raises(typer.BadParameter, match="tagPath"):
        deploy(
            environment="staging", project_root=project, namespace="", context="",
            image_repository="", tag="main-2", force=False, dry_run=False, render=False,
        )


def test_gitops_noop_when_already_at_tag(project: Path, fluxcd_repo: Path, capsys: pytest.CaptureFixture) -> None:
    _write_gitops_config(project, fluxcd_repo)
    deploy(
        environment="staging", project_root=project, namespace="", context="",
        image_repository="", tag="main-1", force=False, dry_run=False, render=False,
    )
    assert "nothing to do" in capsys.readouterr().out


def test_gitops_dry_run_touches_nothing(project: Path, fluxcd_repo: Path, capsys: pytest.CaptureFixture) -> None:
    _write_gitops_config(project, fluxcd_repo)
    deploy(
        environment="staging", project_root=project, namespace="", context="",
        image_repository="", tag="main-5", force=False, dry_run=True, render=False,
    )
    out = capsys.readouterr().out
    assert "would set" in out
    assert "tag: main-1" in _promoted_file(fluxcd_repo, "main")  # unchanged
