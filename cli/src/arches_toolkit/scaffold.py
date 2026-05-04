"""Shared scaffolding helpers for ``arches-toolkit create``.

The command layer in ``commands/create.py`` delegates everything concrete
(path resolution, version selection, token rendering, file writing) to
this module so it can be unit-tested without spinning up Typer.

Templates live at::

    arches_toolkit/_data/templates/<major.minor>/<kind>/…

Files ending in ``.tmpl`` are run through :class:`string.Template`; all
other files are copied verbatim. Relative paths inside each ``<kind>``
tree are preserved under the target.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from string import Template

from ._util import package_data_path

log = logging.getLogger(__name__)

TEMPLATES_DATA = "templates"


@dataclass(frozen=True)
class Target:
    """Where a scaffold should write files, and what it should be named after."""

    root: Path
    """Root dir files are written *into* (a project dir, an app dir, or cwd)."""

    package: str
    """Python package name — e.g. ``mything`` or ``arches_demo``."""

    arches_version: str
    """Selected Arches major.minor (e.g. ``"8.1"``)."""

    is_app: bool
    """True when the target is an Arches application package, not a project."""


# --------------------------------------------------------------------------- #
# Version detection
# --------------------------------------------------------------------------- #


_ARCHES_REQ_RE = re.compile(
    r"""^\s*arches\b        # dep name
        [^0-9]*             # operators / whitespace
        (?P<major>\d+)\.(?P<minor>\d+)""",
    re.VERBOSE,
)


def _available_template_versions() -> list[tuple[int, int]]:
    root = package_data_path(TEMPLATES_DATA)
    out: list[tuple[int, int]] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        m = re.fullmatch(r"(\d+)\.(\d+)", child.name)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    out.sort()
    return out


def _parse_major_minor(version: str) -> tuple[int, int]:
    m = re.match(r"(\d+)\.(\d+)", version)
    if not m:
        raise ValueError(f"not a major.minor version: {version!r}")
    return int(m.group(1)), int(m.group(2))


def _detect_from_pyproject(project_root: Path) -> str | None:
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return None
    # stdlib tomllib (3.11+) — the CLI already requires-python >= 3.11
    import tomllib

    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return None
    deps: list[str] = []
    deps.extend(data.get("project", {}).get("dependencies", []) or [])
    for group in (data.get("project", {}).get("optional-dependencies") or {}).values():
        deps.extend(group or [])
    for spec in deps:
        m = _ARCHES_REQ_RE.match(spec)
        if m:
            return f"{m.group('major')}.{m.group('minor')}"
    return None


def detect_arches_version(
    *,
    explicit: str | None,
    project_root: Path,
) -> str:
    """Choose an Arches major.minor for template selection.

    Precedence: ``--arches-version`` flag → project ``pyproject.toml`` →
    ``ARCHES_VERSION`` env var → latest packaged template set.

    When the selected version has no exact template set we fall back to the
    closest lower available set (warning). If no set is lower, the lowest
    available set is used.
    """
    available = _available_template_versions()
    if not available:
        raise RuntimeError("no template sets shipped under _data/templates/")

    def _pick(requested: str) -> str:
        req = _parse_major_minor(requested)
        if req in available:
            return f"{req[0]}.{req[1]}"
        lower = [v for v in available if v <= req]
        chosen = lower[-1] if lower else available[0]
        log.warning(
            "no template set for arches %s; using %s.%s",
            requested, chosen[0], chosen[1],
        )
        return f"{chosen[0]}.{chosen[1]}"

    if explicit:
        return _pick(explicit)
    from_pyproject = _detect_from_pyproject(project_root)
    if from_pyproject:
        return _pick(from_pyproject)
    env = os.environ.get("ARCHES_VERSION")
    if env:
        return _pick(env)
    latest = available[-1]
    return f"{latest[0]}.{latest[1]}"


# --------------------------------------------------------------------------- #
# Target resolution
# --------------------------------------------------------------------------- #


def _read_env_var(env_path: Path, key: str) -> str | None:
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return None


def _is_arches_app(dir_: Path) -> tuple[bool, str | None]:
    """Return ``(True, package)`` iff ``dir_`` looks like an Arches application."""
    if not dir_.is_dir():
        return False, None
    for child in dir_.iterdir():
        if not child.is_dir() or not child.name.startswith("arches_"):
            continue
        apps_py = child / "apps.py"
        if apps_py.exists() and "is_arches_application" in apps_py.read_text(
            encoding="utf-8", errors="ignore"
        ):
            return True, child.name
    return False, None


def _is_project(dir_: Path) -> str | None:
    """Return PROJECT_PACKAGE iff ``dir_`` looks like a toolkit project root."""
    if not dir_.is_dir():
        return None
    package = _read_env_var(dir_ / ".env", "PROJECT_PACKAGE")
    if package and (dir_ / package / "settings.py").exists():
        return package
    candidate = dir_ / dir_.name / "settings.py"
    if candidate.exists():
        return dir_.name
    return None


def _walk_up(start: Path):
    """Yield ``start`` and each parent up to the filesystem root."""
    cur = start.resolve()
    while True:
        yield cur
        if cur.parent == cur:
            return
        cur = cur.parent


def _find_nearest_app(start: Path) -> tuple[Path, str] | None:
    for d in _walk_up(start):
        ok, package = _is_arches_app(d)
        if ok and package:
            return d, package
    return None


def _find_nearest_project(start: Path) -> tuple[Path, str] | None:
    for d in _walk_up(start):
        package = _is_project(d)
        if package:
            return d, package
    return None


def resolve_target(
    *,
    cwd: Path,
    app_dir: Path | None,
    arches_version: str | None,
) -> Target:
    """Resolve where a ``create`` command should write.

    Walks up from ``cwd`` to find the nearest Arches application or project
    root. If both a project and an app are found along the path, the one
    closer to ``cwd`` wins — running inside an app dir nested in a project
    targets the app. Pass ``app_dir`` to override.

    Raises ``ValueError`` with a user-facing message if no marker is found.
    """
    if app_dir is not None:
        root = app_dir.resolve()
        ok, package = _is_arches_app(root)
        if not ok or package is None:
            raise ValueError(
                f"{root}: not an Arches application package "
                "(expected arches_<name>/apps.py containing is_arches_application)"
            )
        return Target(
            root=root,
            package=package,
            arches_version=detect_arches_version(
                explicit=arches_version, project_root=root
            ),
            is_app=True,
        )

    start = cwd.resolve()
    app_hit = _find_nearest_app(start)
    proj_hit = _find_nearest_project(start)

    # Prefer whichever is deeper (closer to cwd). One must contain the other
    # since both are ancestors of `start`, so is_relative_to settles ties.
    pick_app = app_hit and (
        proj_hit is None or app_hit[0].is_relative_to(proj_hit[0])
    )
    if pick_app:
        root, package = app_hit
        return Target(
            root=root,
            package=package,
            arches_version=detect_arches_version(
                explicit=arches_version, project_root=root
            ),
            is_app=True,
        )
    if proj_hit:
        root, package = proj_hit
        return Target(
            root=root,
            package=package,
            arches_version=detect_arches_version(
                explicit=arches_version, project_root=root
            ),
            is_app=False,
        )
    raise ValueError(
        f"{start}: not inside a toolkit project or Arches application — "
        "cd into one, or pass --app <dir> to target an application."
    )


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


_PASCAL_BOUNDARY = re.compile(r"(?:^|_)(.)")


def derive_tokens(name: str, **extra: str) -> dict[str, str]:
    """Produce the standard token set from ``name`` plus ad-hoc overrides."""
    pascal = _PASCAL_BOUNDARY.sub(lambda m: m.group(1).upper(), name)
    camel = pascal[:1].lower() + pascal[1:] if pascal else ""
    package_dashed = name.replace("_", "-")
    tokens = {
        "name": name,
        "NameCamel": pascal,
        "nameCamel": camel,
        "package": extra.get("package", name),
        "package_dashed": package_dashed,
        "uuid": str(uuid.uuid4()),
        "slug": extra.get("slug", package_dashed),
        "icon": extra.get("icon", "fa fa-puzzle-piece"),
        "datatype": extra.get("datatype", "string"),
        "class_name": extra.get("class_name", f"{pascal}"),
        "function_type": extra.get("function_type", "node"),
        "filter_type": extra.get("filter_type", "filter"),
    }
    tokens.update(extra)
    return tokens


def template_root(arches_version: str, kind: str) -> Path:
    """Absolute path to ``_data/templates/<version>/<kind>/`` (must exist)."""
    root = package_data_path(TEMPLATES_DATA) / arches_version / kind
    if not root.exists():
        raise FileNotFoundError(
            f"no template set for kind={kind!r} at arches {arches_version}"
        )
    return root


def _iter_template_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def plan_writes(
    template_dir: Path,
    target_dir: Path,
    tokens: dict[str, str],
) -> list[tuple[Path, Path, bool]]:
    """Return ``[(src, dst, is_template), …]`` pairs for every file to emit.

    Both ``<path>`` components are rendered through :class:`string.Template`,
    so template trees may contain ``${name}`` / ``${package}`` in directory
    and file names.
    """
    out: list[tuple[Path, Path, bool]] = []
    for src in _iter_template_files(template_dir):
        rel = src.relative_to(template_dir)
        rel_rendered = Template(str(rel)).safe_substitute(tokens)
        is_template = rel_rendered.endswith(".tmpl")
        if is_template:
            rel_rendered = rel_rendered[: -len(".tmpl")]
        dst = target_dir / rel_rendered
        out.append((src, dst, is_template))
    return out


def render_and_write(
    template_dir: Path,
    target_dir: Path,
    tokens: dict[str, str],
    *,
    force: bool,
) -> list[Path]:
    """Materialise ``template_dir`` into ``target_dir`` using ``tokens``.

    Returns the list of files written (absolute paths). Raises
    ``FileExistsError`` if any destination already exists and ``force`` is
    False — the check happens up-front so partial writes are avoided.
    """
    writes = plan_writes(template_dir, target_dir, tokens)
    if not force:
        existing = [dst for _, dst, _ in writes if dst.exists()]
        if existing:
            joined = "\n  ".join(str(p) for p in existing)
            raise FileExistsError(
                f"would overwrite existing files (use --force):\n  {joined}"
            )
    written: list[Path] = []
    for src, dst, is_template in writes:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if is_template:
            text = src.read_text(encoding="utf-8")
            rendered = Template(text).safe_substitute(tokens)
            dst.write_text(rendered, encoding="utf-8")
        else:
            shutil.copyfile(src, dst)
        written.append(dst)
    return written
