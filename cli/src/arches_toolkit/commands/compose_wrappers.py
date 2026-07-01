"""``arches-toolkit`` entry points onto ``docker compose``.

`compose` is the generic escape hatch — it runs any compose subcommand
against the canonical packaged ``-f`` stack + interpolation env, so commands
that need the files (`up`, `build`, `config`) work without the project tree
carrying them. `manage` is sugar for ``python manage.py …`` in the web
container.

The per-subcommand wrappers (`logs`/`ps`/`exec`/`restart`/`down`/`build`)
were removed: once ``COMPOSE_PROJECT_NAME`` is in the project ``.env``
(written by ``init``, self-healed here), the label-based subcommands work as
plain ``docker compose ps/logs/exec/restart/down`` from the project root,
and anything else goes through ``arches-toolkit compose``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Sequence

import typer

from .. import _compose, _output


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
    # Persist the project name so raw `docker compose` targets the same stack.
    _compose.ensure_project_name(project_root)
    argv = _compose.base_argv(project_root) + list(subcommand_argv)
    _output.cmd(argv)
    completed = subprocess.run(argv, env=_compose.compose_env(project_root))
    raise typer.Exit(completed.returncode)


def compose(
    ctx: typer.Context,
    project_root: Path = typer.Option(Path("."), "--project-root"),
) -> None:
    """Run any ``docker compose`` subcommand against the packaged stack.

    Everything after ``compose`` is passed through verbatim, e.g.
    ``arches-toolkit compose up -d`` / ``arches-toolkit compose config`` /
    ``arches-toolkit compose down -v``.
    """
    _require_project(project_root)
    _run_compose(project_root, ctx.args)


def manage(
    ctx: typer.Context,
    service: str = typer.Option(
        "web", "--service",
        help="Service whose python/manage.py to run (default: web)",
    ),
    project_root: Path = typer.Option(Path("."), "--project-root"),
) -> None:
    """Run a Django management command (``python manage.py …``) inside ``web``."""
    _require_project(project_root)
    _run_compose(project_root, ["exec", service, "python", "manage.py", *ctx.args])
