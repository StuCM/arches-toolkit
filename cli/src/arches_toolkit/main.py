"""Entry point for the ``arches-toolkit`` CLI."""

from __future__ import annotations

import logging

import typer

from . import __version__
from . import _output
from .commands import add_app as add_app_cmd
from .commands import compose_wrappers
from .commands import create as create_cmd
from .commands import dev as dev_cmd
from .commands import init as init_cmd
from .commands import migrate as migrate_cmd
from .commands import patch as patch_cmd
from .commands import setup_db as setup_db_cmd
from .commands import install as install_cmd
from .commands import list_apps as list_apps_cmd
from .commands import switch_mode as switch_mode_cmd
from .commands import sync_apps as sync_apps_cmd

app = typer.Typer(
    name="arches-toolkit",
    no_args_is_help=True,
    help="Tooling for Flax & Teal Arches projects",
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"arches-toolkit {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Verbose output: full command lines + INFO logging",
    ),
) -> None:
    """Top-level options shared across subcommands."""
    _output.set_verbose(verbose)
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


# Top-level commands.
app.command("init", help="Scaffold a new Arches project ready for `arches-toolkit dev`")(init_cmd.init)
app.command(
    "migrate",
    help="Convert an existing Arches project to arches-toolkit shape",
)(migrate_cmd.migrate)
app.command(
    "setup-db",
    help="One-time setup_db: drop+rebuild project DB, ES indexes, system settings",
)(setup_db_cmd.setup_db)
app.command("add-app", help="Add an Arches application to apps.yaml")(add_app_cmd.add_app)
app.command("sync-apps", help="Apply apps.yaml changes to pyproject.toml + INSTALLED_APPS")(
    sync_apps_cmd.sync_apps
)
app.command(
    "switch-mode",
    help="Switch an app between release and develop mode (clones / safety-checks)",
)(switch_mode_cmd.switch_mode)
app.command(
    "install",
    help="Install the project and all apps from apps.yaml into the venv volume",
)(install_cmd.install)
app.command(
    "list",
    help="Show apps from apps.yaml with their mode, source, and per-dev install state",
)(list_apps_cmd.list_apps)
app.command(
    "dev",
    help="Start the dev stack (detached, with readiness milestones); edits live-reload via bind mounts",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)(dev_cmd.dev)

# compose: generic escape hatch + named sugar (logs / ps / exec / restart / down / build)
_passthrough = {"allow_extra_args": True, "ignore_unknown_options": True}
app.command("compose", help="Run any `docker compose` subcommand against the packaged stack", context_settings=_passthrough)(compose_wrappers.compose)
app.command("logs", help="Tail `docker compose logs` for the project", context_settings=_passthrough)(compose_wrappers.logs)
app.command("ps", help="List project containers (`docker compose ps`)", context_settings=_passthrough)(compose_wrappers.ps)
app.command("exec", help="Exec a command in a running service", context_settings=_passthrough)(compose_wrappers.exec_)
app.command("restart", help="Restart services (`docker compose restart`)", context_settings=_passthrough)(compose_wrappers.restart)
app.command("down", help="Stop and remove project containers", context_settings=_passthrough)(compose_wrappers.down)
app.command("build", help="Build project images without starting", context_settings=_passthrough)(compose_wrappers.build)
app.command("manage", help="Run `python manage.py …` inside the web container", context_settings=_passthrough)(compose_wrappers.manage)

# create group.
app.add_typer(create_cmd.app, name="create")

# patch group.
app.add_typer(patch_cmd.app, name="patch")


if __name__ == "__main__":  # pragma: no cover
    app()
