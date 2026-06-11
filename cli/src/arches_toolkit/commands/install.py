"""``arches-toolkit install`` — install (or refresh) the project and its apps.

Idempotent. Reads ``apps.yaml``; runs ``uv pip install`` inside the dev image
against the persistent ``venv`` named volume so the install survives container
recreation:

* Release-mode apps come in via the project's own ``[project.dependencies]``,
  resolved from the project's pyproject + uv.lock — one ``uv pip install -e .``
  in the container handles the project itself plus all release apps.
* Develop-mode apps install editable from the permanent ``/workspace`` mount
  (``..:/workspace`` in compose.dev.yaml), one ``uv pip install -e
  /workspace/<dirname>`` per app.

When the web service is up, installs go via ``compose exec`` and finish with
``compose restart web worker api`` — never recreates a container, so volume
config changes can't desync. When web is down or crashlooping, falls back to
``compose run --rm --entrypoint sh web``; the named ``venv`` volume persists
across container lifetimes, so a subsequent ``arches-toolkit dev`` boots into
a populated venv.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer

from .. import apps_manifest as manifest_mod
from .._clone import develop_repo_dirname
from . import compose_wrappers as cw


def _docker_or_die() -> None:
    if shutil.which("docker") is None:
        raise typer.BadParameter("docker not found on PATH")


def _web_is_running(project_root: Path) -> bool:
    """Return True iff the web service has at least one running container."""
    argv = cw._compose_base_argv(project_root) + [
        "ps", "--status", "running", "--services",
    ]
    result = subprocess.run(
        argv, env=cw._compose_env(),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False
    return "web" in result.stdout.split()


def _build_install_script(
    develop_apps: list[manifest_mod.AppEntry],
    project_root: Path,
) -> str:
    """Shell script body that installs the project + editable overrides.

    The base ``uv pip install -e .`` covers all apps in pyproject — release
    apps and develop apps alike (develop renders as ``pkg @ git+repo@ref``).
    For each develop app where a sibling clone exists locally, force-reinstall
    editable from ``/workspace/<dir>`` so edits are live. Develop apps with
    no local clone are left as the from-git install — that's the expected
    state for colleagues who haven't switched to working on this app yet.
    """
    lines = [
        "set -eux",
        "uv pip install --python /venv/bin/python --prerelease=allow -e .",
    ]
    workspace_root = project_root.resolve().parent
    for entry in develop_apps:
        dirname = develop_repo_dirname(entry)
        if not (workspace_root / dirname).exists():
            continue
        lines.append(
            "uv pip install --python /venv/bin/python --prerelease=allow "
            f"--force-reinstall -e /workspace/{dirname}"
        )
    return "\n".join(lines)


def _run_install(project_root: Path, script: str, *, web_up: bool) -> None:
    base = cw._compose_base_argv(project_root)
    if web_up:
        argv = base + ["exec", "-T", "web", "sh", "-euc", script]
    else:
        argv = base + ["run", "--rm", "--entrypoint", "sh", "web", "-euc", script]
    typer.echo(f"+ {' '.join(argv[:6])} … (install script)")
    completed = subprocess.run(argv, env=cw._compose_env())
    if completed.returncode != 0:
        raise typer.Exit(completed.returncode)


def _run_migrate(project_root: Path) -> None:
    """Apply any pending Django migrations — a fast no-op when there are none.

    Newly installed apps ship migrations that nothing else applies on a
    running stack (init only migrates on cold start), so install owns it.
    """
    argv = cw._compose_base_argv(project_root) + [
        "exec", "-T", "web", "python", "manage.py", "migrate", "--noinput",
    ]
    typer.echo(f"+ {' '.join(argv[-6:])}")
    completed = subprocess.run(argv, env=cw._compose_env())
    if completed.returncode != 0:
        raise typer.Exit(completed.returncode)


def _restart_services(project_root: Path) -> None:
    argv = cw._compose_base_argv(project_root) + [
        "restart", "web", "worker", "api",
    ]
    typer.echo(f"+ {' '.join(argv[-5:])}")
    subprocess.run(argv, env=cw._compose_env())


def install(
    project_root: Path = typer.Option(
        Path("."), "--project-root",
        help="Project root containing pyproject.toml + apps.yaml",
        show_default=False,
    ),
    no_restart: bool = typer.Option(
        False, "--no-restart",
        help="Skip the post-install `compose restart web worker api`",
    ),
    no_migrate: bool = typer.Option(
        False, "--no-migrate",
        help="Skip applying pending Django migrations after the install",
    ),
) -> None:
    """Install the project and all apps from apps.yaml into the venv volume."""
    _docker_or_die()
    project_root = cw._require_project(project_root)

    manifest_path = project_root / manifest_mod.DEFAULT_MANIFEST_NAME
    manifest = manifest_mod.load(manifest_path)
    develop = list(manifest_mod.iter_develop(manifest))

    script = _build_install_script(develop, project_root)

    web_up = _web_is_running(project_root)
    _run_install(project_root, script, web_up=web_up)

    if web_up and not no_migrate:
        _run_migrate(project_root)
    if web_up and not no_restart:
        _restart_services(project_root)
    elif not web_up:
        typer.echo(
            "\nVenv populated; web wasn't running, so nothing to restart. "
            "Bring services up with `arches-toolkit dev` — init applies any "
            "pending migrations on boot."
        )
