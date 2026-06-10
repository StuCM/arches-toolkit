"""``arches-toolkit list`` — show every app in apps.yaml with install status.

Pure inspection; no docker, no network. Each row shows what *will* land in
the container after the next ``install`` run, derived from apps.yaml + the
host filesystem (sibling clone presence). Useful both as a per-dev "what's
my local state" view and a team "what's WIP vs released" view of apps.yaml.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .. import apps_manifest as manifest_mod
from .._clone import clone_path
from ..apps_manifest import AppEntry
from .sync_apps import DEFAULT_DEVELOP_REF


def _install_state(entry: AppEntry, project_root: Path) -> str:
    if entry.mode == "release":
        if entry.source == "git":
            return "git (release ref)"
        return "pypi"
    # develop
    if clone_path(entry, project_root).exists():
        return "[bold green]editable (clone)[/]"
    return "git (team branch)"


def _ref_for_display(entry: AppEntry) -> str:
    if entry.ref:
        return entry.ref
    if entry.mode == "develop":
        return f"[dim]{DEFAULT_DEVELOP_REF} (default)[/]"
    return "[dim]-[/]"


def _source_for_display(entry: AppEntry) -> str:
    if entry.mode == "develop":
        # In develop mode the install is always git+clone regardless of
        # `source` — `source` is only the *release*-mode origin. Annotate it
        # so a `pypi` source next to an editable install doesn't read as a
        # contradiction.
        origin = f"[dim]{entry.source} (release origin)[/]"
        return f"{origin} · {entry.repo}" if entry.repo else origin
    if entry.repo:
        return f"{entry.source} · {entry.repo}"
    return entry.source


def list_apps(
    manifest_path: Path = typer.Option(
        Path("apps.yaml"), "--manifest",
        help="Path to apps.yaml (default: ./apps.yaml)",
        show_default=False,
    ),
    project_root: Path = typer.Option(
        Path("."), "--project-root",
        help="Project root (default: cwd)",
        show_default=False,
    ),
) -> None:
    """List apps from apps.yaml with their per-dev install state."""
    if not manifest_path.exists():
        raise typer.BadParameter(
            f"{manifest_path}: not found — nothing to list"
        )
    manifest = manifest_mod.load(manifest_path)

    console = Console()
    if not manifest.apps:
        console.print(f"[dim]{manifest_path} has no apps yet.[/]")
        return

    table = Table(
        title=f"apps.yaml ({len(manifest.apps)} app{'s' if len(manifest.apps) != 1 else ''})",
        title_justify="left",
        show_lines=False,
    )
    table.add_column("Package", no_wrap=True, style="bold")
    table.add_column("Mode", no_wrap=True)
    table.add_column("Source")
    table.add_column("Ref", no_wrap=True)
    table.add_column("Cloned", no_wrap=True, justify="center")
    table.add_column("Install state")

    for entry in manifest.apps:
        cloned = (
            "[green]✓[/]"
            if entry.mode == "develop" and clone_path(entry, project_root).exists()
            else "[dim]-[/]"
        )
        mode_styled = (
            f"[yellow]{entry.mode}[/]" if entry.mode == "develop" else entry.mode
        )
        table.add_row(
            entry.package,
            mode_styled,
            _source_for_display(entry),
            _ref_for_display(entry),
            cloned,
            _install_state(entry, project_root),
        )

    console.print(table)

    # Brief footer summarising develop-mode local state — useful at a glance.
    develop = [a for a in manifest.apps if a.mode == "develop"]
    if develop:
        cloned_count = sum(
            1 for a in develop if clone_path(a, project_root).exists()
        )
        console.print(
            f"\n[dim]develop apps: {cloned_count}/{len(develop)} cloned locally"
            f" — `arches-toolkit switch-mode <pkg> develop` to clone & work on one.[/]"
        )
