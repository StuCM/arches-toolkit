"""Thin ``arches-toolkit`` wrappers around ``docker compose`` subcommands.

Each one sets up the toolkit-specific env vars and ``-f`` flags so users
don't have to. All pass extra args straight through to compose.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Sequence

import typer

PACKAGE_DATA = "arches_toolkit._data"
BASELINE = ("compose.yaml", "compose.dev.yaml")
PROJECT_OVERLAYS = ("compose.apps.yaml", "compose.extras.yaml")


def _package_data_path(name: str) -> Path:
    p = Path(str(resources.files(PACKAGE_DATA).joinpath(name)))
    if not p.exists():
        raise typer.BadParameter(f"package data missing: {name}")
    return p


def _compose_base_argv(project_root: Path) -> list[str]:
    """Build the ``docker compose --project-directory … -f … -f …`` prefix."""
    project_root = project_root.resolve()
    compose_files = [_package_data_path(n) for n in BASELINE]
    compose_files += [
        project_root / n for n in PROJECT_OVERLAYS if (project_root / n).exists()
    ]
    argv = ["docker", "compose", "--project-directory", str(project_root)]
    for f in compose_files:
        argv += ["-f", str(f)]
    return argv


def _compose_env() -> dict[str, str]:
    env = os.environ.copy()
    env["ARCHES_TOOLKIT_DOCKERFILE"] = str(_package_data_path("Dockerfile"))
    env["ARCHES_TOOLKIT_INIT_SQL"] = str(_package_data_path("init.sql"))
    return env


def _require_project(project_root: Path) -> Path:
    project_root = project_root.resolve()
    if not (project_root / ".env").exists():
        raise typer.BadParameter(
            f"{project_root}: no .env found — run from a project root or pass --project-root"
        )
    return project_root


def _run_compose(project_root: Path, subcommand_argv: Sequence[str]) -> None:
    if shutil.which("docker") is None:
        raise typer.BadParameter("docker not found on PATH")
    argv = _compose_base_argv(project_root) + list(subcommand_argv)
    typer.echo(f"+ {' '.join(argv)}")
    completed = subprocess.run(argv, env=_compose_env())
    raise typer.Exit(completed.returncode)


def logs(
    ctx: typer.Context,
    project_root: Path = typer.Option(Path("."), "--project-root"),
) -> None:
    """Tail ``docker compose logs`` for the project."""
    _require_project(project_root)
    _run_compose(project_root, ["logs", *ctx.args])


def ps(
    ctx: typer.Context,
    project_root: Path = typer.Option(Path("."), "--project-root"),
) -> None:
    """List project containers (``docker compose ps``)."""
    _require_project(project_root)
    _run_compose(project_root, ["ps", *ctx.args])


def exec_(
    ctx: typer.Context,
    service: str = typer.Argument(..., help="Service to exec into"),
    project_root: Path = typer.Option(Path("."), "--project-root"),
) -> None:
    """Exec a command in a running service (``docker compose exec SERVICE …``)."""
    _require_project(project_root)
    _run_compose(project_root, ["exec", service, *ctx.args])


def restart(
    ctx: typer.Context,
    project_root: Path = typer.Option(Path("."), "--project-root"),
) -> None:
    """Restart services (``docker compose restart …``)."""
    _require_project(project_root)
    _run_compose(project_root, ["restart", *ctx.args])


def down(
    ctx: typer.Context,
    volumes: bool = typer.Option(
        False, "--volumes", "-v", help="Remove named volumes too (destructive)"
    ),
    project_root: Path = typer.Option(Path("."), "--project-root"),
) -> None:
    """Stop and remove project containers (``docker compose down``)."""
    _require_project(project_root)
    extra = ["-v"] if volumes else []
    _run_compose(project_root, ["down", *extra, *ctx.args])


def build(
    ctx: typer.Context,
    project_root: Path = typer.Option(Path("."), "--project-root"),
) -> None:
    """Build project images (``docker compose build``). No services start."""
    _require_project(project_root)
    _run_compose(project_root, ["build", *ctx.args])
