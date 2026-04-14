"""``arches-toolkit patch`` — list, renew, status, start, finish."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .. import patches as patches_mod
from ..patches import PATCHES_RELDIR, PatchHeader, PatchHeaderError

app = typer.Typer(no_args_is_help=True, help="Inspect and maintain Arches patch series")

console = Console()

DEFAULT_ARCHES_REPO = "https://github.com/archesproject/arches.git"
DEFAULT_ARCHES_REF = "stable/8.1.0"


def _scratch_root() -> Path:
    override = os.environ.get("ARCHES_TOOLKIT_SCRATCH")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "arches-toolkit" / "patches"


def _scratch_dir(name: str) -> Path:
    return _scratch_root() / name


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        raise typer.Exit(r.returncode)


def _marker_field(text: str, key: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(f"{key}: "):
            return line[len(key) + 2:].strip()
    return None


def _sanitise_patch_name(name: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name):
        raise typer.BadParameter(
            f"patch name {name!r} must be lowercase kebab/snake-case "
            "(letters, digits, '.', '_', '-')"
        )
    return name


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


@app.command("start")
def start(
    name: str = typer.Argument(..., help="Patch name (kebab-case, no number prefix)"),
    arches_ref: str = typer.Option(DEFAULT_ARCHES_REF, "--arches-ref"),
    arches_repo: str = typer.Option(DEFAULT_ARCHES_REPO, "--arches-repo"),
    force: bool = typer.Option(False, "--force", help="Re-clone if the scratch already exists"),
) -> None:
    """Set up a scratch clone of Arches ready for a new patch."""
    if shutil.which("git") is None:
        raise typer.BadParameter("git not found on PATH")
    name = _sanitise_patch_name(name)

    scratch = _scratch_dir(name)
    if scratch.exists():
        if not force:
            raise typer.BadParameter(
                f"{scratch}: already exists — edit there, then run `patch finish {name}`, "
                "or pass --force to reclone"
            )
        shutil.rmtree(scratch)

    scratch.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--depth", "50", "--branch", arches_ref, arches_repo, str(scratch)])
    _run(["git", "config", "user.email", "toolkit@flaxandteal.co.uk"], cwd=scratch)
    _run(["git", "config", "user.name", "arches-toolkit"], cwd=scratch)
    _run(["git", "checkout", "-b", f"toolkit-patch/{name}"], cwd=scratch)

    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=scratch, capture_output=True, text=True, check=True,
    ).stdout.strip()
    marker = f"base_sha: {base_sha}\ntoolkit_root: {Path.cwd()}\n"
    (scratch / ".arches-toolkit-base").write_text(marker, encoding="utf-8")

    typer.echo("")
    typer.echo(f"Scratch ready: {scratch}")
    typer.echo(f"Branch:        toolkit-patch/{name}")
    typer.echo("")
    typer.echo("Next:")
    typer.echo(f"  1. cd {scratch}")
    typer.echo("  2. edit files, then git commit (one or more commits)")
    typer.echo(f"  3. arches-toolkit patch finish {name}")


@app.command("finish")
def finish(
    name: str = typer.Argument(..., help="Patch name passed to `patch start`"),
    upstream: str | None = typer.Option(None, "--upstream", help="Upstream PR URL"),
    reason: str | None = typer.Option(None, "--reason", help="One-line justification"),
    number: int | None = typer.Option(None, "--number", min=1, help="Override the NNNN prefix"),
    patches_dir: Path | None = typer.Option(None, "--patches-dir"),
    keep_scratch: bool = typer.Option(
        True, "--keep-scratch/--remove-scratch",
        help="Leave the scratch clone in place (default) or delete it",
    ),
) -> None:
    """Export the topmost commit in the scratch as docker/base/patches/NNNN-<name>.patch."""
    if shutil.which("git") is None:
        raise typer.BadParameter("git not found on PATH")
    name = _sanitise_patch_name(name)
    scratch = _scratch_dir(name)
    if not (scratch / ".git").is_dir():
        raise typer.BadParameter(
            f"{scratch}: not a git clone — run `arches-toolkit patch start {name}` first"
        )

    base_marker = scratch / ".arches-toolkit-base"
    if not base_marker.exists():
        raise typer.BadParameter(
            f"{scratch}: no base marker — re-run `arches-toolkit patch start {name}`"
        )
    marker_text = base_marker.read_text(encoding="utf-8")
    base_sha = _marker_field(marker_text, "base_sha") or marker_text.strip()
    toolkit_root = _marker_field(marker_text, "toolkit_root")

    r = subprocess.run(
        ["git", "rev-list", "--count", f"{base_sha}..HEAD"],
        cwd=scratch, capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip().isdigit() or int(r.stdout.strip()) == 0:
        raise typer.BadParameter(
            f"{scratch}: no new commits since `patch start` — commit first, then re-run"
        )

    if patches_dir is not None:
        pdir = patches_dir
    elif toolkit_root:
        pdir = Path(toolkit_root) / PATCHES_RELDIR
    else:
        pdir = _resolve_patches_dir(None)
    pdir.mkdir(parents=True, exist_ok=True)

    # Remove any prior patch with the same name so we don't collect duplicates.
    for existing in pdir.glob(f"[0-9][0-9][0-9][0-9]-{name}.patch"):
        existing.unlink()

    n = number if number is not None else patches_mod.next_patch_number(pdir)
    prefix = f"{n:04d}"
    target = pdir / f"{prefix}-{name}.patch"

    r = subprocess.run(
        ["git", "format-patch", "-1", "--stdout", "--no-signature", "HEAD"],
        cwd=scratch, capture_output=True, text=True,
    )
    if r.returncode != 0:
        typer.echo(r.stderr, err=True)
        raise typer.Exit(r.returncode)

    patched = patches_mod.inject_headers(r.stdout, upstream=upstream, reason=reason)
    target.write_text(patched, encoding="utf-8")

    typer.echo(f"wrote {target.relative_to(Path.cwd()) if target.is_relative_to(Path.cwd()) else target}")
    if not keep_scratch:
        shutil.rmtree(scratch)
        typer.echo(f"removed {scratch}")
