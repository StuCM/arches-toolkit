"""``arches-toolkit add-app`` — add an entry to ``apps.yaml``.

No network calls. Idempotent: running with the same arguments twice is a
no-op the second time. Re-running with different fields updates the existing
entry rather than appending a duplicate.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import typer

from .. import apps_manifest as manifest_mod
from ..apps_manifest import AppEntry


class Source(str, Enum):
    pypi = "pypi"
    git = "git"


class Mode(str, Enum):
    release = "release"
    develop = "develop"


def add_app(
    package: str = typer.Argument(..., help="Python package name (e.g. arches-her)"),
    source: Source = typer.Option(Source.pypi, "--source", help="Where to fetch the package"),
    version: str | None = typer.Option(
        None, "--version", help="Version specifier (release mode, pypi source)"
    ),
    repo: str | None = typer.Option(
        None, "--repo", help="Git repository URL (required when --source git)"
    ),
    ref: str | None = typer.Option(
        None, "--ref", help="Git ref (branch/tag/sha) when --source git"
    ),
    mode: Mode = typer.Option(
        Mode.release, "--mode", help="release: pinned dep; develop: bind-mounted editable install"
    ),
    manifest_path: Path = typer.Option(
        Path("apps.yaml"),
        "--manifest",
        help="Path to apps.yaml (default: ./apps.yaml)",
        show_default=False,
    ),
) -> None:
    if source == Source.git and not repo:
        raise typer.BadParameter("--repo is required when --source=git")
    if source == Source.pypi and repo:
        raise typer.BadParameter("--repo is only valid when --source=git")

    entry = AppEntry(
        package=package,
        source=source.value,
        version=version,
        repo=repo,
        ref=ref,
        mode=mode.value,
    )

    manifest = manifest_mod.load(manifest_path)
    action, _previous = manifest.upsert(entry)
    manifest_mod.save(manifest, manifest_path)

    if action == "added":
        typer.echo(f"Added {package} to {manifest_path}")
    elif action == "updated":
        typer.echo(f"Updated {package} in {manifest_path}")
    else:
        typer.echo(f"{package} already present in {manifest_path}; no changes")

    if action != "unchanged":
        typer.echo("")
        typer.echo("Next steps:")
        if mode == Mode.release:
            typer.echo("  1. arches-toolkit sync-apps")
            typer.echo("  2. uv sync   # or: docker compose exec web uv sync")
        else:
            typer.echo("  1. arches-toolkit sync-apps")
            typer.echo("  2. arches-toolkit dev   # picks up compose.apps.yaml")
        django_app = package.replace("-", "_")
        typer.echo("")
        typer.echo("If your settings.py does not already inherit this app, add to INSTALLED_APPS:")
        typer.echo(f'    "{django_app}",')
