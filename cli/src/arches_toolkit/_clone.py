"""Clone management for develop-mode apps.

Develop-mode apps live as a sibling clone of the project root, exposed to the
dev container via the permanent ``..:/workspace`` mount in compose.dev.yaml;
``arches-toolkit install`` then force-reinstalls each editable from
``/workspace/<dir>``. This module owns the path convention and the safety
checks for that clone — shared between
``add-app`` (clone on first develop entry) and ``switch-mode`` (clone on
release→develop, gate on develop→release).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from .apps_manifest import AppEntry


def develop_repo_dirname(entry: AppEntry) -> str:
    """Sibling directory name for a develop-mode clone.

    Precedence: explicit ``path`` on the entry → derived from repo URL →
    package name. The override covers cases where the user checked out the
    clone under a non-default name (e.g. a branch-named dir like ``2.0.x/``).
    """
    if entry.path:
        return entry.path
    if entry.repo:
        last = entry.repo.rstrip("/").rsplit("/", 1)[-1]
        if last.endswith(".git"):
            last = last[:-4]
        if last:
            return last
    return entry.package


def clone_path(entry: AppEntry, project_root: Path) -> Path:
    return project_root.resolve().parent / develop_repo_dirname(entry)


def ensure_clone(entry: AppEntry, project_root: Path) -> tuple[Path, str]:
    """Clone the entry's repo to its sibling location if not already present.

    Returns ``(path, action)`` where ``action`` is ``"cloned"`` or ``"exists"``.
    Idempotent: an existing directory is left alone — no fetch, no checkout.
    The clone is the user's working tree from here on.
    """
    if not entry.repo:
        raise typer.BadParameter(
            f"{entry.package}: cannot clone — no `repo` set on the apps.yaml "
            "entry. Pass --repo URL."
        )
    path = clone_path(entry, project_root)
    if path.exists():
        return path, "exists"
    # `ref` is the install spec for clone-less colleagues only — it never
    # dictates the local clone's branch. The clone lands on the repo's
    # default branch; check out whatever you want to work on yourself.
    cmd = ["git", "clone", entry.repo, str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise typer.BadParameter(
            f"git clone failed for {entry.package}:\n{result.stderr.rstrip()}"
        )
    return path, "cloned"


def check_clone_safety(entry: AppEntry, project_root: Path) -> list[str]:
    """Report unpushed/uncommitted work in the clone, if any.

    Returns a list of human-readable issue strings — empty list means the
    clone (or its absence) is safe to leave behind. Stashes are deliberately
    not checked.
    """
    path = clone_path(entry, project_root)
    if not path.exists() or not (path / ".git").exists():
        return []

    issues: list[str] = []

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path, capture_output=True, text=True,
    )
    if status.stdout.strip():
        issues.append(
            f"uncommitted changes in {path}:\n    "
            + "\n    ".join(status.stdout.rstrip().splitlines())
        )

    upstream = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "@{u}"],
        cwd=path, capture_output=True, text=True,
    )
    if upstream.returncode != 0:
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=path, capture_output=True, text=True,
        )
        if head.returncode == 0:
            issues.append(
                f"no upstream configured for HEAD in {path} — cannot verify "
                "commits are pushed"
            )
    else:
        unpushed = subprocess.run(
            ["git", "rev-list", "@{u}..HEAD"],
            cwd=path, capture_output=True, text=True,
        )
        lines = [line for line in unpushed.stdout.splitlines() if line.strip()]
        if lines:
            issues.append(
                f"{len(lines)} unpushed commit(s) on "
                f"{upstream.stdout.strip()} in {path}"
            )

    return issues
