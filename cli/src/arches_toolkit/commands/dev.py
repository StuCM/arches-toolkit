"""``arches-toolkit dev`` — wrap ``docker compose up --watch``.

Auto-discovers compose overlay files relative to the current working
directory and forwards any extra arguments straight to ``docker compose``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer

OVERLAY_ORDER = (
    "compose.yaml",
    "compose.dev.yaml",
    "compose.apps.yaml",
    "compose.extras.yaml",
)


def _discover_overlays(project_root: Path) -> list[Path]:
    return [project_root / name for name in OVERLAY_ORDER if (project_root / name).exists()]


def _build_argv(
    overlays: list[Path],
    extra: list[str],
    *,
    build: bool,
) -> list[str]:
    argv = ["docker", "compose"]
    for f in overlays:
        argv += ["-f", str(f)]
    argv += ["up", "--watch"]
    if build:
        argv.append("--build")
    argv += list(extra)
    return argv


def dev(
    ctx: typer.Context,
    build: bool = typer.Option(False, "--build", help="Force rebuild before bringing up"),
    project_root: Path = typer.Option(
        Path("."),
        "--project-root",
        help="Project root containing compose.yaml (default: cwd)",
        show_default=False,
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the docker compose invocation without executing"
    ),
) -> None:
    """Run ``docker compose up --watch`` with auto-discovered overlays."""
    if shutil.which("docker") is None:
        raise typer.BadParameter("docker not found on PATH")
    overlays = _discover_overlays(project_root)
    if not overlays:
        raise typer.BadParameter(
            f"{project_root}: no compose.yaml found — run from a project root"
        )
    argv = _build_argv(overlays, list(ctx.args), build=build)
    if dry_run:
        typer.echo(" ".join(argv))
        return
    typer.echo(f"+ {' '.join(argv)}")
    completed = subprocess.run(argv, cwd=os.fspath(project_root))
    raise typer.Exit(completed.returncode)
