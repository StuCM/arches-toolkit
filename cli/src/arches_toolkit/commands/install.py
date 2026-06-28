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

When the web service is up, installs go via ``compose exec``, then pending
migrations are applied, frontend_configuration is regenerated, and the run
finishes with ``compose restart web worker api webpack`` — never recreates a
container, so volume config changes can't desync. When web is down or
crashlooping, falls back to
``compose run --rm --entrypoint sh web``; the named ``venv`` volume persists
across container lifetimes, so a subsequent ``arches-toolkit dev`` boots into
a populated venv.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path

import typer

from .. import _compose
from .. import _output
from .. import apps_manifest as manifest_mod
from .._clone import develop_repo_dirname
from . import compose_wrappers as cw


def _docker_or_die() -> None:
    if shutil.which("docker") is None:
        raise typer.BadParameter("docker not found on PATH")


def _web_is_running(project_root: Path) -> bool:
    """Return True iff the web service has at least one running container."""
    argv = _compose.base_argv(project_root) + [
        "ps", "--status", "running", "--services",
    ]
    result = subprocess.run(
        argv, env=_compose.compose_env(project_root),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False
    return "web" in result.stdout.split()


def _build_install_script(
    develop_apps: list[manifest_mod.AppEntry],
    project_root: Path,
    verbose: bool = False,
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
        "set -eux" if verbose else "set -eu",
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
    base = _compose.base_argv(project_root)
    if web_up:
        argv = base + ["exec", "-T", "web", "sh", "-euc", script]
    else:
        argv = base + ["run", "--rm", "--entrypoint", "sh", "web", "-euc", script]
    _output.stage("Installing project + apps into the venv")
    _output.cmd(argv)
    completed = subprocess.run(argv, env=_compose.compose_env(project_root))
    if completed.returncode != 0:
        raise typer.Exit(completed.returncode)


def _npm_overlay_specs(
    develop_apps: list[manifest_mod.AppEntry],
    project_root: Path,
) -> list[str]:
    """`name@spec` args for the npm local overlay.

    The npm analogue of the editable /workspace install: for each npm-managed
    develop app with a sibling clone, install the *clone's* declared deps into
    the project node_modules `--no-save` — so a dep added locally is usable
    before it's pushed (push to share, not to use). Committed files stay
    untouched; a volume rebuild reverts to the committed state until install
    re-runs.
    """
    workspace_root = project_root.resolve().parent
    specs: list[str] = []
    for entry in develop_apps:
        if not entry.npm:
            continue
        pkg_json = workspace_root / develop_repo_dirname(entry) / "package.json"
        if not pkg_json.exists():
            continue
        try:
            deps = json.loads(pkg_json.read_text(encoding="utf-8")).get("dependencies", {})
        except ValueError:
            typer.echo(f"warning: {pkg_json}: invalid JSON — skipping npm overlay", err=True)
            continue
        specs += [f"{name}@{spec}" for name, spec in deps.items()]
    return specs


def _build_npm_script(overlay_specs: list[str], verbose: bool = False) -> str:
    """Shell script for the webpack container: reconcile the committed npm
    layer (managed git entries from sync-apps), apply the local overlay, then
    freshen the install stamp so the webpack startup hook doesn't re-run a
    plain `npm install` that could prune the overlay.
    """
    lines = [
        "set -eux" if verbose else "set -eu",
        "cd /app",
        "npm install --no-audit --no-fund",
    ]
    if overlay_specs:
        quoted = " ".join(shlex.quote(s) for s in overlay_specs)
        lines.append(f"npm install --no-save --no-audit --no-fund {quoted}")
    lines.append("touch node_modules/.arches-toolkit-install-stamp")
    return "\n".join(lines)


def _run_npm_install(project_root: Path, script: str) -> None:
    # --user app: the webpack service starts as root (to chown the volume)
    # but node_modules must stay app-owned.
    argv = _compose.base_argv(project_root) + [
        "exec", "-T", "--user", "app", "webpack", "sh", "-euc", script,
    ]
    _output.stage("Installing frontend dependencies (npm)")
    _output.cmd(argv)
    completed = subprocess.run(argv, env=_compose.compose_env(project_root))
    if completed.returncode != 0:
        raise typer.Exit(completed.returncode)


# Mirrors the init service's warm-start REGEN in compose.dev.yaml — keep in sync.
FRONTEND_REGEN_SNIPPET = """\
import django
django.setup()
from arches.app.utils.frontend_configuration_utils.generate_frontend_configuration import generate_frontend_configuration
generate_frontend_configuration()
print("frontend_configuration: regenerated")
"""


def _regen_frontend_configuration(project_root: Path) -> None:
    """Regenerate webpack-metadata.json (and friends) after an install.

    ARCHES_APPLICATIONS_PATHS bakes in where each app's module *resolves* —
    site-packages for release installs, /workspace for editable develop
    clones — so any add-app or switch-mode (either direction) leaves webpack
    compiling stale paths until this runs and webpack restarts on it.
    Failure is a warning, not fatal: the stack still works for backend code.
    """
    argv = _compose.base_argv(project_root) + [
        "exec", "-T", "web", "python", "-c", FRONTEND_REGEN_SNIPPET,
    ]
    _output.stage("Regenerating frontend configuration")
    _output.cmd(argv)
    completed = subprocess.run(argv, env=_compose.compose_env(project_root))
    if completed.returncode != 0:
        typer.echo(
            "warning: frontend_configuration regen failed — webpack may compile "
            "stale app paths; `arches-toolkit down && arches-toolkit dev` to recover"
        )


def _run_migrate(project_root: Path) -> None:
    """Apply any pending Django migrations — a fast no-op when there are none.

    Newly installed apps ship migrations that nothing else applies on a
    running stack (init only migrates on cold start), so install owns it.
    """
    argv = _compose.base_argv(project_root) + [
        "exec", "-T", "web", "python", "manage.py", "migrate", "--noinput",
    ]
    _output.stage("Applying database migrations")
    _output.cmd(argv)
    completed = subprocess.run(argv, env=_compose.compose_env(project_root))
    if completed.returncode != 0:
        raise typer.Exit(completed.returncode)


def _restart_services(project_root: Path) -> None:
    # webpack restarts too: a running dev server can't re-read its config, so
    # the freshly regenerated app paths only take effect on a process restart.
    # Cheap beyond the inherent first compile — the startup stamp check skips
    # npm install when package.json is unchanged.
    argv = _compose.base_argv(project_root) + [
        "restart", "web", "worker", "api", "webpack",
    ]
    _output.stage("Restarting services (web, worker, api, webpack)")
    _output.cmd(argv)
    subprocess.run(argv, env=_compose.compose_env(project_root))


def install(
    project_root: Path = typer.Option(
        Path("."), "--project-root",
        help="Project root containing pyproject.toml + apps.yaml",
        show_default=False,
    ),
    no_restart: bool = typer.Option(
        False, "--no-restart",
        help="Skip the post-install frontend regen + `compose restart web worker api webpack`",
    ),
    no_migrate: bool = typer.Option(
        False, "--no-migrate",
        help="Skip applying pending Django migrations after the install",
    ),
    no_npm: bool = typer.Option(
        False, "--no-npm",
        help="Skip the frontend (npm) dependency install for npm-managed apps",
    ),
) -> None:
    """Install the project and all apps from apps.yaml into the venv volume."""
    _docker_or_die()
    project_root = cw._require_project(project_root)

    manifest_path = project_root / manifest_mod.DEFAULT_MANIFEST_NAME
    manifest = manifest_mod.load(manifest_path)
    develop = list(manifest_mod.iter_develop(manifest))
    npm_managed = any(a.npm for a in manifest.apps)

    script = _build_install_script(develop, project_root, verbose=_output.is_verbose())

    web_up = _web_is_running(project_root)
    _run_install(project_root, script, web_up=web_up)

    if web_up and npm_managed and not no_npm:
        overlay = _npm_overlay_specs(develop, project_root)
        _run_npm_install(
            project_root,
            _build_npm_script(overlay, verbose=_output.is_verbose()),
        )
    if web_up and not no_migrate:
        _run_migrate(project_root)
    if web_up and not no_restart:
        _regen_frontend_configuration(project_root)
        _restart_services(project_root)
    elif not web_up:
        typer.echo(
            "\nVenv populated; web wasn't running, so nothing to restart. "
            "Bring services up with `arches-toolkit dev` — init applies any "
            "pending migrations on boot."
        )
