"""``arches-toolkit patch`` — list, renew, status."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .. import patches as patches_mod
from ..patches import PATCHES_RELDIR, PatchHeader, PatchHeaderError

app = typer.Typer(no_args_is_help=True, help="Inspect and maintain Arches patch series")

console = Console()


def _resolve_patches_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    return Path.cwd() / PATCHES_RELDIR


def _ensure_patches_dir(path: Path) -> None:
    if not path.is_dir():
        raise typer.BadParameter(
            f"{path}: not found — run from the toolkit repo root, or pass --patches-dir"
        )


def _format_review(h: PatchHeader) -> tuple[str, str]:
    if h.last_reviewed is None:
        return "—", "—"
    days = h.days_since_review
    return h.last_reviewed.isoformat(), f"{days}d"


def _render_table(headers: list[PatchHeader], *, with_status_column: bool) -> Table:
    table = Table(title=f"{len(headers)} patch(es)")
    table.add_column("file", overflow="fold")
    table.add_column("subject", overflow="fold")
    table.add_column("upstream", overflow="fold")
    table.add_column("last-reviewed")
    table.add_column("age")
    if with_status_column:
        table.add_column("PR state")
    return table


@app.command("list")
def list_(
    patches_dir: Path | None = typer.Option(
        None, "--patches-dir", help="Override patches directory (default: docker/base/patches)"
    ),
) -> None:
    """List patches with header metadata."""
    pdir = _resolve_patches_dir(patches_dir)
    _ensure_patches_dir(pdir)
    headers = patches_mod.parse_all(pdir)
    if not headers:
        typer.echo(f"no patches in {pdir}")
        return
    table = _render_table(headers, with_status_column=False)
    for h in headers:
        last, age = _format_review(h)
        table.add_row(h.name, h.subject or "—", h.upstream or "—", last, age)
    console.print(table)


@app.command("renew")
def renew(
    patch_name: str = typer.Argument(..., help="Patch filename (e.g. 0001-foo.patch)"),
    patches_dir: Path | None = typer.Option(
        None, "--patches-dir", help="Override patches directory (default: docker/base/patches)"
    ),
) -> None:
    """Bump ``Last-reviewed:`` in the named patch to today."""
    pdir = _resolve_patches_dir(patches_dir)
    _ensure_patches_dir(pdir)
    target = pdir / patch_name
    if not target.exists():
        raise typer.BadParameter(f"{target}: not found")
    try:
        today = patches_mod.renew_last_reviewed(target)
    except PatchHeaderError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    typer.echo(f"renewed {patch_name}: Last-reviewed: {today.isoformat()}")


@app.command("status")
def status(
    patches_dir: Path | None = typer.Option(
        None, "--patches-dir", help="Override patches directory (default: docker/base/patches)"
    ),
) -> None:
    """Like ``list``, but query the GitHub API for upstream PR state."""
    import httpx  # local import — only command that needs network

    pdir = _resolve_patches_dir(patches_dir)
    _ensure_patches_dir(pdir)
    headers = patches_mod.parse_all(pdir)
    if not headers:
        typer.echo(f"no patches in {pdir}")
        return

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        typer.echo(
            "warning: no GH_TOKEN/GITHUB_TOKEN set; skipping GitHub PR state lookups",
            err=True,
        )

    pr_states: dict[str, str] = {}
    if token:
        client_headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        with httpx.Client(timeout=10.0, headers=client_headers) as client:
            for h in headers:
                pr = h.upstream_pr
                if pr is None:
                    pr_states[h.name] = "n/a"
                    continue
                owner, repo, num = pr
                url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{num}"
                try:
                    r = client.get(url)
                except httpx.HTTPError as e:
                    pr_states[h.name] = f"error: {e.__class__.__name__}"
                    continue
                if r.status_code == 404:
                    pr_states[h.name] = "not-found"
                    continue
                if r.status_code >= 400:
                    pr_states[h.name] = f"http {r.status_code}"
                    continue
                data = r.json()
                if data.get("merged"):
                    pr_states[h.name] = "merged"
                else:
                    pr_states[h.name] = data.get("state", "unknown")

    table = _render_table(headers, with_status_column=True)
    for h in headers:
        last, age = _format_review(h)
        state = pr_states.get(h.name, "skipped" if not token else "—")
        table.add_row(h.name, h.subject or "—", h.upstream or "—", last, age, state)
    console.print(table)
