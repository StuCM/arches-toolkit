"""``arches-toolkit setup-db`` — one-time DB + ES + system-settings setup.

Runs ``python manage.py setup_db --force`` inside the running ``web`` service.
This is **destructive**: it drops and rebuilds the database, deletes and
re-creates Elasticsearch indexes, then loads Arches' default system-settings
graph and data so ``/settings/`` works.

Run once after the first ``arches-toolkit dev`` brings the stack up. Re-run
only when you genuinely want to wipe the project's data.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from importlib import resources
from pathlib import Path

import typer

PACKAGE_DATA = "arches_toolkit._data"
BASELINE = ("compose.yaml", "compose.dev.yaml")


def _package_data_path(name: str) -> Path:
    p = Path(str(resources.files(PACKAGE_DATA).joinpath(name)))
    if not p.exists():
        raise typer.BadParameter(f"package data missing: {name}")
    return p


def setup_db(
    project_root: Path = typer.Option(
        Path("."), "--project-root",
        help="Project root containing .env (default: cwd)",
        show_default=False,
    ),
    dev_users: bool = typer.Option(
        False, "--dev-users",
        help="Pass --dev to setup_db so it adds test users (admin/admin etc.)",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip the destructive-action confirmation prompt",
    ),
    service: str = typer.Option(
        "web", "--service",
        help="Compose service to exec setup_db inside (default: web)",
    ),
) -> None:
    """One-time setup_db --force: drops the project's DB and rebuilds it.

    Loads Arches' default system-settings graph + data so ``/settings/`` works.
    """
    if shutil.which("docker") is None:
        raise typer.BadParameter("docker not found on PATH")
    project_root = project_root.resolve()
    if not (project_root / ".env").exists():
        raise typer.BadParameter(
            f"{project_root}: no .env found — run from the project root or pass --project-root"
        )

    if not yes:
        typer.echo(
            "WARNING: this drops and rebuilds the project database, deletes ES "
            "indexes, and reseeds Arches' default system settings."
        )
        if not typer.confirm("Continue?"):
            raise typer.Exit(1)

    dockerfile = _package_data_path("Dockerfile")
    init_sql = _package_data_path("init.sql")
    compose_files = [_package_data_path(name) for name in BASELINE]

    setup_db_args = ["python", "manage.py", "setup_db", "--force"]
    if dev_users:
        setup_db_args.append("--dev")

    argv = ["docker", "compose", "--project-directory", str(project_root)]
    for f in compose_files:
        argv += ["-f", str(f)]
    argv += ["exec", service, *setup_db_args]

    env = os.environ.copy()
    env["ARCHES_TOOLKIT_DOCKERFILE"] = str(dockerfile)
    env["ARCHES_TOOLKIT_INIT_SQL"] = str(init_sql)

    typer.echo(f"+ {' '.join(argv)}")
    completed = subprocess.run(argv, env=env)
    raise typer.Exit(completed.returncode)
