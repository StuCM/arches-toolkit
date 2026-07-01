"""Shared helpers for building ``docker compose`` invocations.

The baseline compose files and the project Dockerfile ship as CLI package
data; the project tree never carries them. These helpers assemble the
canonical ``docker compose`` command — file list, interpolation env, and
project name — used by ``dev`` and by the compose pass-through commands, so
there is a single source of truth for the stack definition.

The project name matters for native use: with a toolkit-managed
``COMPOSE_PROJECT_NAME`` in the project ``.env``, raw ``docker compose
ps/logs/exec/restart/down`` resolve the running stack by label from the
project root with no ``-f`` files at all (those commands are label-based).
``up``/``build``/``config`` still need the packaged files and run through
``arches-toolkit compose`` / ``dev``.
"""

from __future__ import annotations

import os
import re
from importlib import resources
from pathlib import Path

import typer

PACKAGE_DATA = "arches_toolkit._data"
BASELINE = ("compose.yaml", "compose.dev.yaml")
PROJECT_OVERLAYS = ("compose.extras.yaml",)
ARCHES_SRC_OVERLAY = "compose.arches-src.yaml"


def package_data_path(name: str) -> Path:
    p = Path(str(resources.files(PACKAGE_DATA).joinpath(name)))
    if not p.exists():
        raise typer.BadParameter(f"package data missing: {name}")
    return p


def env_file_var(env_path: Path, key: str) -> str | None:
    """Minimal ``.env`` reader — returns the value for ``key``, or ``None``.

    Docker compose reads ``.env`` automatically for YAML interpolation, but the
    Python CLI doesn't get that for free. We look up specific keys that gate
    CLI-level behaviour (ARCHES_SRC, COMPOSE_PROJECT_NAME).
    """
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return None


def resolve_arches_src(project_root: Path) -> str | None:
    """ARCHES_SRC from the shell env (wins) or the project ``.env``."""
    return os.environ.get("ARCHES_SRC") or env_file_var(
        project_root / ".env", "ARCHES_SRC"
    )


def compose_files(project_root: Path) -> list[Path]:
    """Canonical ``-f`` stack: packaged baseline + project extras + arches-src."""
    files = [package_data_path(n) for n in BASELINE]
    files += [
        project_root / n for n in PROJECT_OVERLAYS if (project_root / n).exists()
    ]
    if resolve_arches_src(project_root):
        files.append(package_data_path(ARCHES_SRC_OVERLAY))
    return files


def compose_env(project_root: Path) -> dict[str, str]:
    """Process env for compose: Dockerfile path + ARCHES_SRC when set."""
    env = os.environ.copy()
    env["ARCHES_TOOLKIT_DOCKERFILE"] = str(package_data_path("Dockerfile"))
    arches_src = resolve_arches_src(project_root)
    if arches_src:
        env["ARCHES_SRC"] = arches_src
    return env


def normalize_project_name(raw: str) -> str:
    """Approximate docker compose's default project-name derivation.

    Compose lowercases the directory basename and keeps only ``[a-z0-9_-]``,
    stripping leading separators. Matching it means an explicit
    ``COMPOSE_PROJECT_NAME`` equals the directory-derived name, so adding the
    line never orphans an already-running stack.
    """
    s = re.sub(r"[^a-z0-9_-]", "", raw.lower()).lstrip("_-")
    return s or "arches"


def project_name(project_root: Path) -> str:
    """Explicit ``COMPOSE_PROJECT_NAME`` if set (env or .env), else the
    normalized directory basename (compose's own default)."""
    explicit = os.environ.get("COMPOSE_PROJECT_NAME") or env_file_var(
        project_root / ".env", "COMPOSE_PROJECT_NAME"
    )
    return explicit or normalize_project_name(project_root.resolve().name)


def ensure_project_name(project_root: Path) -> str:
    """Ensure ``.env`` carries ``COMPOSE_PROJECT_NAME`` so raw ``docker
    compose`` targets the same stack as the toolkit.

    Appends the directory-derived name (compose's own default, so no orphaned
    stack) when absent and ``.env`` exists; prints a one-time notice. Returns
    the resolved name. A no-op beyond reading when already set or when ``.env``
    is missing.
    """
    env_path = project_root / ".env"
    existing = env_file_var(env_path, "COMPOSE_PROJECT_NAME")
    if existing:
        return existing
    name = normalize_project_name(project_root.resolve().name)
    if env_path.exists():
        text = env_path.read_text(encoding="utf-8")
        if text and not text.endswith("\n"):
            text += "\n"
        text += (
            "\n# arches-toolkit: explicit compose project name so raw "
            "`docker compose` targets this stack\n"
            f"COMPOSE_PROJECT_NAME={name}\n"
        )
        env_path.write_text(text, encoding="utf-8")
        typer.echo(f"  + COMPOSE_PROJECT_NAME={name} added to .env")
    return name


def base_argv(project_root: Path) -> list[str]:
    """``docker compose --project-directory … -f … -f …`` prefix."""
    argv = ["docker", "compose", "--project-directory", str(project_root.resolve())]
    for f in compose_files(project_root):
        argv += ["-f", str(f)]
    return argv
