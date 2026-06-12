"""``arches-toolkit add-app`` — register an app in ``apps.yaml`` and install it.

End-to-end: upserts ``apps.yaml`` → (develop) clones the sibling working tree
→ runs ``sync-apps`` → runs ``install`` so the new app is live in the venv
volume. Idempotent — re-running with the same args is a no-op.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import typer

from .. import apps_manifest as manifest_mod
from .._clone import ensure_clone
from ..apps_manifest import AppEntry
from . import install as install_cmd
from . import sync_apps as sync_apps_cmd


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
        None, "--ref",
        help="Git ref (branch/tag/sha) — the install spec for git/develop apps; "
             "for develop apps this is what clone-less colleagues resolve, not "
             "your local clone's branch",
    ),
    mode: Mode = typer.Option(
        Mode.release, "--mode", help="release: pinned dep; develop: bind-mounted editable install"
    ),
    npm: bool | None = typer.Option(
        None, "--npm/--no-npm",
        help="App also declares frontend deps in a root package.json — manage a "
             "git entry for it in the project's package.json (auto-detected from "
             "the clone for develop apps when unset)",
    ),
    manifest_path: Path = typer.Option(
        Path("apps.yaml"),
        "--manifest",
        help="Path to apps.yaml (default: ./apps.yaml)",
        show_default=False,
    ),
    no_sync: bool = typer.Option(
        False, "--no-sync",
        help="Skip running `sync-apps` after upsert (also implies --no-install)",
    ),
    no_install: bool = typer.Option(
        False, "--no-install",
        help="Skip running `install` (e.g. when bootstrapping before `dev`)",
    ),
) -> None:
    if source == Source.git and not repo:
        raise typer.BadParameter("--repo is required when --source=git")
    if source == Source.pypi and repo and mode != Mode.develop:
        raise typer.BadParameter(
            "--repo with --source=pypi is only valid in develop mode "
            "(where it tells the toolkit where to clone the working tree)"
        )
    if mode == Mode.develop and not repo and source == Source.pypi:
        raise typer.BadParameter(
            "--repo URL is required when adding a develop-mode app from pypi "
            "— we need somewhere to clone from"
        )

    entry = AppEntry(
        package=package,
        source=source.value,
        version=version,
        repo=repo,
        ref=ref,
        mode=mode.value,
        npm=bool(npm),
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

    if mode == Mode.develop:
        path, clone_action = ensure_clone(entry, manifest_path.parent)
        if clone_action == "cloned":
            typer.echo(f"Cloned {entry.repo} → {path}")
        else:
            typer.echo(f"Clone already exists at {path} — leaving untouched")
        # Auto-detect npm participation from the working tree when not stated
        # explicitly: a root package.json means the app declares frontend deps.
        if npm is None and (path / "package.json").exists():
            entry.npm = True
            manifest.upsert(entry)
            manifest_mod.save(manifest, manifest_path)
            typer.echo(
                f"{package}: root package.json detected — npm entry will be "
                "managed in the project's package.json (npm: true in apps.yaml)"
            )

    project_root = manifest_path.parent

    if no_sync:
        return

    typer.echo("")
    sync_apps_cmd.sync_apps(
        manifest_path=manifest_path,
        project_root=project_root,
        no_lock=False,
        no_installed_apps=False,
    )

    if no_install:
        return

    typer.echo("")
    install_cmd.install(
        project_root=project_root, no_restart=False, no_migrate=False, no_npm=False
    )
