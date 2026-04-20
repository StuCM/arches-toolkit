"""``arches-toolkit migrate`` — convert an existing Arches project.

Glue around ``init --force``, ``add-app`` and ``sync-apps`` plus legacy-docker
removal. Non-destructive by default: prints a plan, prompts for confirmation,
can ``--dry-run``. No new logic that isn't already in those subcommands — this
is orchestration.
"""

from __future__ import annotations

import ast
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tomlkit
import typer

from .. import apps_manifest as manifest_mod
from ..apps_manifest import AppEntry
from . import init as init_cmd
from . import sync_apps as sync_apps_cmd

CORE_ARCHES_MODULES = {
    "arches",
    "arches.app",
    "arches.app.models",
    "arches.management",
}


@dataclass
class DetectedApp:
    package: str                     # hyphenated (PEP 503) for apps.yaml
    django_module: str               # underscored, as found in INSTALLED_APPS
    source: str = "pypi"             # "pypi" or "git"
    repo: Optional[str] = None
    ref: Optional[str] = None
    in_installed_apps: bool = False
    in_pyproject: bool = False

    @property
    def warnings(self) -> list[str]:
        w: list[str] = []
        if self.in_installed_apps and not self.in_pyproject:
            w.append(
                f"{self.package}: in INSTALLED_APPS but not in pyproject.toml — "
                "probably transitive; declaring explicitly in apps.yaml"
            )
        if self.source == "git":
            w.append(
                f"{self.package}: git-source dep parsed from pyproject "
                f"(repo={self.repo} ref={self.ref}) — review before sync-apps"
            )
        return w


@dataclass
class Context:
    target: Path
    package: str
    settings_path: Path
    apps: list[DetectedApp] = field(default_factory=list)
    legacy_docker: Optional[Path] = None
    legacy_makefile: Optional[Path] = None
    root_dockerfile: Optional[Path] = None
    has_env: bool = False
    has_apps_yaml: bool = False


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _is_external_arches_module(module: str) -> bool:
    if not (module.startswith("arches_") or module.startswith("arches-")):
        return False
    if module in CORE_ARCHES_MODULES:
        return False
    return True


def _find_package(target: Path) -> str:
    candidates = [
        p.name for p in sorted(target.iterdir())
        if p.is_dir()
        and (p / "__init__.py").exists()
        and (p / "settings.py").exists()
    ]
    if not candidates:
        raise typer.BadParameter(
            f"{target}: no arches package found (needs a dir with __init__.py + settings.py)"
        )
    if len(candidates) > 1:
        raise typer.BadParameter(
            f"{target}: multiple package candidates {candidates} — rerun with --target-dir "
            "pointing at the specific project root"
        )
    return candidates[0]


def _parse_installed_apps(settings_path: Path) -> set[str]:
    """Return every string literal assigned (or appended) to INSTALLED_APPS.

    Walks both ``INSTALLED_APPS = (...)`` and ``INSTALLED_APPS += (...)``,
    including conditional branches (``if AZURE: INSTALLED_APPS = (..., "storages")``).
    Over-inclusion is fine — worst case, the user deletes a line from apps.yaml.
    """
    tree = ast.parse(settings_path.read_text(encoding="utf-8"))
    found: set[str] = set()

    def _collect(node: ast.AST) -> None:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                found.add(sub.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "INSTALLED_APPS":
                    _collect(node.value)
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "INSTALLED_APPS":
                _collect(node.value)
    return found


def _parse_pyproject_deps(
    pyproject: Path,
) -> dict[str, tuple[str, Optional[str], Optional[str]]]:
    """Return ``{canonical_name: (source, repo, ref)}`` for every dep."""
    doc = tomlkit.parse(pyproject.read_text(encoding="utf-8"))
    project = doc.get("project")
    if project is None:
        return {}
    result: dict[str, tuple[str, Optional[str], Optional[str]]] = {}
    for dep in project.get("dependencies", []):
        s = str(dep).strip()
        if " @ " in s:
            name, url = (part.strip() for part in s.split(" @ ", 1))
            if url.startswith("git+"):
                git_url = url[4:]
                repo, sep, ref = git_url.rpartition("@")
                if not sep:
                    repo, ref = git_url, None
                result[_canonical(name)] = ("git", repo, ref or None)
            else:
                # Direct URL but not git — treat as pypi; user will review.
                result[_canonical(name)] = ("pypi", None, None)
        else:
            name = s
            for sep in ("[", "==", "!=", ">=", "<=", "~=", ">", "<", " ", ";"):
                i = name.find(sep)
                if i != -1:
                    name = name[:i]
            result[_canonical(name.strip())] = ("pypi", None, None)
    return result


def _detect(target: Path) -> Context:
    package = _find_package(target)
    settings_path = target / package / "settings.py"

    installed = _parse_installed_apps(settings_path)
    external_modules = {m for m in installed if _is_external_arches_module(m)}

    pyproject_path = target / "pyproject.toml"
    pyproject_deps: dict[str, tuple[str, Optional[str], Optional[str]]] = {}
    if pyproject_path.exists():
        pyproject_deps = _parse_pyproject_deps(pyproject_path)

    # Union: INSTALLED_APPS external arches modules + pyproject arches-* deps.
    canonical_to_module: dict[str, str] = {
        _canonical(m): m for m in external_modules
    }
    for canon in list(pyproject_deps):
        if canon.startswith("arches-") and canon not in canonical_to_module:
            canonical_to_module[canon] = canon.replace("-", "_")

    apps: list[DetectedApp] = []
    for canon, django_module in sorted(canonical_to_module.items()):
        src, repo, ref = pyproject_deps.get(canon, ("pypi", None, None))
        apps.append(
            DetectedApp(
                package=canon,
                django_module=django_module,
                source=src,
                repo=repo,
                ref=ref,
                in_installed_apps=django_module in external_modules,
                in_pyproject=canon in pyproject_deps,
            )
        )

    legacy_docker = target / "docker"
    legacy_makefile = target / "Makefile"
    root_dockerfile = target / "Dockerfile"

    return Context(
        target=target,
        package=package,
        settings_path=settings_path,
        apps=apps,
        legacy_docker=legacy_docker if legacy_docker.is_dir() else None,
        legacy_makefile=legacy_makefile if legacy_makefile.is_file() else None,
        root_dockerfile=root_dockerfile if root_dockerfile.is_file() else None,
        has_env=(target / ".env").exists(),
        has_apps_yaml=(target / "apps.yaml").exists(),
    )


def _print_plan(ctx: Context, *, keep_docker: bool, keep_makefile: bool) -> None:
    typer.echo("")
    typer.echo(f"Target:   {ctx.target}")
    typer.echo(f"Package:  {ctx.package}")
    typer.echo("")
    typer.echo("Apps to declare in apps.yaml:")
    if not ctx.apps:
        typer.echo("  (none — INSTALLED_APPS has no external arches-* modules)")
    for app in ctx.apps:
        src = app.source
        extra = f" repo={app.repo}@{app.ref}" if app.source == "git" else ""
        typer.echo(f"  - {app.package} ({src}{extra})")
    typer.echo("")

    warnings: list[str] = []
    for app in ctx.apps:
        warnings.extend(app.warnings)
    if ctx.root_dockerfile is not None:
        warnings.append(
            f"found {ctx.root_dockerfile.name} at repo root — toolkit ships its own Dockerfile; "
            "review whether yours is still needed (not touched by migrate)"
        )
    if warnings:
        typer.echo("Warnings:")
        for w in warnings:
            typer.echo(f"  ! {w}")
        typer.echo("")

    typer.echo("Files to add:")
    to_add = []
    if not ctx.has_env:
        to_add.append(".env")
    to_add.append(".dockerignore")
    to_add.append("apps.yaml" if not ctx.has_apps_yaml else "apps.yaml (merge)")
    for f in to_add:
        typer.echo(f"  + {f}")

    typer.echo("Files to modify:")
    typer.echo(f"  ~ {ctx.package}/settings.py    (append env-overrides block, idempotent)")
    typer.echo("  ~ .gitignore                    (append toolkit entries)")
    typer.echo("  ~ pyproject.toml                (managed deps + [tool.arches-toolkit])")

    removals: list[str] = []
    if ctx.legacy_docker is not None and not keep_docker:
        removals.append("docker/")
    if ctx.legacy_makefile is not None and not keep_makefile:
        removals.append("Makefile")
    if removals:
        typer.echo("Files to remove:")
        for f in removals:
            typer.echo(f"  - {f}")


def _execute(ctx: Context, *, keep_docker: bool, keep_makefile: bool) -> None:
    typer.echo("")
    typer.echo(init_cmd._patch_settings(ctx.settings_path))
    typer.echo(
        init_cmd._write_env(
            ctx.target,
            name=ctx.package,
            package=ctx.package,
            toolkit_image="ghcr.io/flaxandteal/arches-toolkit",
            toolkit_tag="latest-arches-stable-8.1.0",
        )
    )
    typer.echo(init_cmd._write_dockerignore(ctx.target))
    typer.echo(init_cmd._ensure_gitignore(ctx.target))

    manifest_path = ctx.target / "apps.yaml"
    manifest = manifest_mod.load(manifest_path)
    for app in ctx.apps:
        entry = AppEntry(
            package=app.package,
            source=app.source,
            repo=app.repo,
            ref=app.ref,
            mode="release",
        )
        action, _ = manifest.upsert(entry)
        typer.echo(f"apps.yaml: {action} {app.package}")
    manifest_mod.save(manifest, manifest_path)

    release = list(manifest_mod.iter_release(manifest))
    develop = list(manifest_mod.iter_develop(manifest))
    typer.echo(sync_apps_cmd._sync_pyproject(release, ctx.target))
    typer.echo(sync_apps_cmd._sync_compose_apps(develop, ctx.target))

    if ctx.legacy_docker is not None and not keep_docker:
        shutil.rmtree(ctx.legacy_docker)
        typer.echo(f"removed {ctx.legacy_docker.name}/")
    if ctx.legacy_makefile is not None and not keep_makefile:
        ctx.legacy_makefile.unlink()
        typer.echo(f"removed {ctx.legacy_makefile.name}")


def _print_next_steps(ctx: Context) -> None:
    typer.echo("")
    typer.echo("Done. Next:")
    typer.echo("  arches-toolkit dev --build       # first build")
    typer.echo("  arches-toolkit setup-db --yes    # seed Arches schema + default system settings")
    typer.echo("  curl -I http://localhost:8000/auth/")


def migrate(
    target_dir: Path = typer.Argument(
        Path("."),
        help="Project root to migrate (default: cwd)",
        show_default=False,
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip interactive confirmation",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the plan and warnings, touch nothing",
    ),
    keep_docker: bool = typer.Option(
        False, "--keep-docker", help="Don't remove the legacy docker/ tree",
    ),
    keep_makefile: bool = typer.Option(
        False, "--keep-makefile", help="Don't remove the project-root Makefile",
    ),
) -> None:
    """Convert an existing Arches project to arches-toolkit shape."""
    target = target_dir.resolve()
    if not target.is_dir():
        raise typer.BadParameter(f"{target}: not a directory")

    ctx = _detect(target)

    already = (
        ctx.has_apps_yaml
        and ctx.has_env
        and ctx.legacy_docker is None
        and ctx.legacy_makefile is None
    )
    if already:
        typer.echo(f"{target}: already migrated (apps.yaml + .env present, no legacy docker/ or Makefile).")
        return

    _print_plan(ctx, keep_docker=keep_docker, keep_makefile=keep_makefile)

    if dry_run:
        return

    if not yes:
        typer.echo("")
        if not typer.confirm("Proceed?", default=False):
            raise typer.Exit(1)

    _execute(ctx, keep_docker=keep_docker, keep_makefile=keep_makefile)
    _print_next_steps(ctx)
