"""``arches-toolkit switch-mode`` — flip an app between release and develop.

release → develop: clones the repo to a sibling of the project root if no
clone exists, then re-runs sync-apps (which renders the app as a git dep in
pyproject) and install (which force-reinstalls it editable from /workspace).

develop → release: refuses if the clone has uncommitted or unpushed work
(override with ``--force``). Never deletes the clone — the directory stays
as the user's working tree, ready for a future switch back.

The ``ref`` field on the apps.yaml entry is the install spec only; we do
not read or write the clone's branch on switch.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import typer

from .. import apps_manifest as manifest_mod
from .._clone import check_clone_safety, clone_path, ensure_clone
from . import install as install_cmd
from . import sync_apps as sync_apps_cmd


class Mode(str, Enum):
    release = "release"
    develop = "develop"


def switch_mode(
    package: str = typer.Argument(..., help="Package name as recorded in apps.yaml"),
    target: Mode = typer.Argument(..., help="Mode to switch to"),
    repo: str | None = typer.Option(
        None, "--repo",
        help="Repo URL to clone (required when switching a pypi-source app to "
             "develop with no recorded repo; persisted onto the apps.yaml entry)",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Switch to release even if the clone has uncommitted or unpushed work",
    ),
    no_sync: bool = typer.Option(
        False, "--no-sync",
        help="Skip the sync-apps step at the end (also implies --no-install)",
    ),
    no_install: bool = typer.Option(
        False, "--no-install",
        help="Skip the install step at the end",
    ),
    manifest_path: Path = typer.Option(
        Path("apps.yaml"), "--manifest",
        help="Path to apps.yaml (default: ./apps.yaml)",
        show_default=False,
    ),
    project_root: Path = typer.Option(
        Path("."), "--project-root",
        help="Project root containing pyproject.toml (default: cwd)",
        show_default=False,
    ),
) -> None:
    manifest = manifest_mod.load(manifest_path)
    entry = manifest.find(package)
    if entry is None:
        raise typer.BadParameter(
            f"{package!r} not found in {manifest_path} — run `arches-toolkit add-app` first"
        )
    # Snapshot for rollback: if sync/install fails after the manifest flip
    # (network down, broken dep, …), restore the previous entry so apps.yaml
    # never claims a state the stack was not converged to.
    prior_entry = entry.to_dict()

    if target == Mode.develop:
        if repo:
            entry.repo = repo
        if not entry.repo:
            raise typer.BadParameter(
                f"{package}: switching to develop needs a repo to clone — pass --repo URL"
            )
        path, action = ensure_clone(entry, project_root)
        if action == "cloned":
            typer.echo(f"Cloned {entry.repo} → {path}")
        else:
            typer.echo(f"Clone already exists at {path} — leaving untouched")
        if entry.mode != "develop":
            entry.mode = "develop"
            manifest_mod.save(manifest, manifest_path)
            typer.echo(f"Set {package} mode → develop in {manifest_path}")
        else:
            # Persist any --repo update even if mode was already develop.
            manifest_mod.save(manifest, manifest_path)
    else:
        if entry.mode != "develop":
            typer.echo(f"{package} is already in release mode — nothing to do")
            return
        issues = check_clone_safety(entry, project_root)
        if issues and not force:
            details = "\n  - ".join(issues)
            raise typer.BadParameter(
                f"Refusing to switch {package} to release — clone has work that "
                f"would be left behind:\n  - {details}\n"
                "(The clone directory is preserved either way; this gate is "
                "to make sure you don't forget about local work. Pass --force "
                "to proceed.)"
            )
        if issues:
            typer.echo("Proceeding despite local work in clone (--force):")
            for i in issues:
                typer.echo(f"  - {i}")
        path = clone_path(entry, project_root)
        if path.exists():
            typer.echo(f"Clone preserved at {path} (not deleted)")
        entry.mode = "release"
        manifest_mod.save(manifest, manifest_path)
        typer.echo(f"Set {package} mode → release in {manifest_path}")

    if no_sync:
        return

    try:
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
        install_cmd.install(project_root=project_root, no_restart=False, no_migrate=False)
    except Exception:
        _rollback(package, prior_entry, manifest_path, project_root)
        raise


def _rollback(
    package: str,
    prior_entry: dict,
    manifest_path: Path,
    project_root: Path,
) -> None:
    """Restore the pre-switch apps.yaml entry and re-sync the project files.

    Best-effort: if the re-sync also fails (e.g. the same network outage that
    broke the forward switch), the manifest is still restored and the user is
    told exactly what to run once the underlying issue is fixed.
    """
    prior_mode = prior_entry.get("mode", "release")
    typer.echo(
        f"\nswitch failed — rolling {package} back to mode: {prior_mode} "
        f"in {manifest_path}",
        err=True,
    )
    manifest = manifest_mod.load(manifest_path)
    manifest.upsert(manifest_mod.AppEntry.from_dict(prior_entry))
    manifest_mod.save(manifest, manifest_path)
    try:
        sync_apps_cmd.sync_apps(
            manifest_path=manifest_path,
            project_root=project_root,
            no_lock=False,
            no_installed_apps=False,
        )
        typer.echo(
            "rolled back: apps.yaml + pyproject restored; the venv was left as "
            "it was. Re-run switch-mode once the underlying problem is fixed.",
            err=True,
        )
    except Exception:
        typer.echo(
            "rollback re-sync also failed (offline?) — apps.yaml is restored; "
            "run `arches-toolkit sync-apps` then `arches-toolkit install` once "
            "connectivity is back.",
            err=True,
        )
