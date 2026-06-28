"""Project-level patch selection — the control plane for which Arches core
patches apply. Modelled on ``apps.yaml``: a manifest plus CLI toggles, with a
two-layer model that mirrors develop-apps.

Two layers:

- **Toolkit series** — patches shipped with the CLI (package data; the
  baseline baked into the base image). Enabled by default.
- **Local overlay** — ``*.patch`` files in the project's ``patches/``
  directory. Enabled by default. *Promote* a local patch into the toolkit
  series to share it (push to share, not to use).

``patches.yaml`` at the project root records *deviations* from the
"everything enabled" baseline — a ``disabled:`` list of patch ids. An absent
or empty manifest means every discovered patch is enabled, so a fresh project
needs no file at all.

Patches are referenced by **id** (the filename stem, e.g.
``0001-frontend_configuration-…``). Selectors accept the full id, the numeric
prefix (``0001`` / ``1``), or any unique substring, so the CLI can offer a
listed, toggle-by-name/number UX without hand-editing files.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import patches as patches_mod

MANIFEST_NAME = "patches.yaml"
LOCAL_PATCHES_DIRNAME = "patches"

TOOLKIT = "toolkit"
LOCAL = "local"


class PatchError(ValueError):
    """Base for patch-management errors surfaced to the CLI."""


class PatchSelectorError(PatchError):
    """Raised when a selector matches zero or multiple patches."""


@dataclass
class PatchEntry:
    id: str  # filename stem
    source: str  # TOOLKIT | LOCAL
    enabled: bool
    path: Path
    header: patches_mod.PatchHeader

    @property
    def subject(self) -> str:
        return self.header.subject or "—"

    @property
    def filename(self) -> str:
        return self.path.name


def manifest_path(project_root: Path) -> Path:
    return project_root / MANIFEST_NAME


def local_patches_dir(project_root: Path) -> Path:
    return project_root / LOCAL_PATCHES_DIRNAME


def _read_manifest(project_root: Path) -> dict:
    p = manifest_path(project_root)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _read_disabled(project_root: Path) -> set[str]:
    data = _read_manifest(project_root)
    return {str(x) for x in (data.get("disabled") or [])}


def _write_disabled(project_root: Path, disabled: set[str]) -> None:
    """Persist the disabled set to ``patches.yaml`` (pruned to known ids).

    Removes the file's ``disabled`` key when empty; writes a header comment so
    the file explains itself.
    """
    p = manifest_path(project_root)
    data = _read_manifest(project_root)
    if disabled:
        data["disabled"] = sorted(disabled)
    else:
        data.pop("disabled", None)

    if not data:
        # Nothing to record — leave (or remove) an empty manifest.
        if p.exists():
            p.unlink()
        return

    header = (
        "# Arches core patches for this project.\n"
        "# Toolkit patches (shipped with the CLI) and local patches (in ./patches/)\n"
        "# are enabled by default; this file records only what's turned off.\n"
        "# Toggle with `arches-toolkit patch enable|disable <id>`.\n"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(header + yaml.safe_dump(data, sort_keys=True), encoding="utf-8")


def _discover(directory: Path, source: str, disabled: set[str]) -> list[PatchEntry]:
    entries: list[PatchEntry] = []
    for path in patches_mod.discover(directory):
        stem = path.stem
        entries.append(
            PatchEntry(
                id=stem,
                source=source,
                enabled=stem not in disabled,
                path=path,
                header=patches_mod.parse_file(path),
            )
        )
    return entries


def load(project_root: Path, *, toolkit_dir: Path | None = None) -> list[PatchEntry]:
    """All known patches (toolkit series + local overlay) with enabled state.

    ``toolkit_dir`` overrides the shipped-patches location (tests).
    """
    disabled = _read_disabled(project_root)
    tdir = toolkit_dir if toolkit_dir is not None else patches_mod.shipped_patches_dir()
    entries = _discover(tdir, TOOLKIT, disabled)
    entries += _discover(local_patches_dir(project_root), LOCAL, disabled)
    return entries


def enabled_patches(project_root: Path, *, toolkit_dir: Path | None = None) -> list[PatchEntry]:
    """The patches to apply, in order (toolkit series first, then local)."""
    return [e for e in load(project_root, toolkit_dir=toolkit_dir) if e.enabled]


def resolve(entries: list[PatchEntry], token: str) -> PatchEntry:
    """Find the single entry a selector token refers to.

    Match order: exact id → numeric prefix (``0001`` / ``1``) → unique
    substring. Raises :class:`PatchSelectorError` on no/ambiguous match.
    """
    exact = [e for e in entries if e.id == token]
    if len(exact) == 1:
        return exact[0]

    if token.isdigit():
        n = int(token)
        numbered = [e for e in entries if e.id[:4].isdigit() and int(e.id[:4]) == n]
        if len(numbered) == 1:
            return numbered[0]
        if len(numbered) > 1:
            raise PatchSelectorError(
                f"{token!r} matches multiple patches: {', '.join(e.id for e in numbered)}"
            )

    subs = [e for e in entries if token in e.id]
    if len(subs) == 1:
        return subs[0]
    if len(subs) > 1:
        raise PatchSelectorError(
            f"{token!r} is ambiguous — matches: {', '.join(e.id for e in subs)}"
        )
    raise PatchSelectorError(f"{token!r} matches no patch")


def set_enabled(
    project_root: Path,
    tokens: list[str],
    *,
    enabled: bool,
    toolkit_dir: Path | None = None,
) -> list[PatchEntry]:
    """Enable/disable patches by selector; persist to ``patches.yaml``.

    Returns the resolved entries (with their *new* state). Raises
    :class:`PatchSelectorError` (before writing anything) on a bad selector.
    """
    entries = load(project_root, toolkit_dir=toolkit_dir)
    known_ids = {e.id for e in entries}
    resolved = [resolve(entries, t) for t in tokens]

    disabled = _read_disabled(project_root) & known_ids  # prune stale ids
    for e in resolved:
        if enabled:
            disabled.discard(e.id)
        else:
            disabled.add(e.id)
    _write_disabled(project_root, disabled)

    return [
        PatchEntry(id=e.id, source=e.source, enabled=enabled, path=e.path, header=e.header)
        for e in resolved
    ]


def _sanitise_stem(name: str) -> str:
    stem = name[:-6] if name.endswith(".patch") else name
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", stem):
        raise PatchError(
            f"patch id {stem!r} must be alphanumeric kebab/snake-case "
            "(letters, digits, '.', '_', '-')"
        )
    return stem


def _prune_disabled_to_known(project_root: Path) -> None:
    known = {e.id for e in load(project_root)}
    _write_disabled(project_root, _read_disabled(project_root) & known)


def add_local(
    project_root: Path,
    src: Path,
    *,
    name: str | None = None,
    force: bool = False,
) -> PatchEntry:
    """Register a ``.patch`` file as a local patch (copies it into ./patches/).

    Enabled by default. Raises :class:`PatchError` on a missing source, a bad
    id, or a name clash (unless ``force``).
    """
    src = Path(src)
    if not src.is_file():
        raise PatchError(f"{src}: not found")
    stem = _sanitise_stem(name or src.name)
    dest_dir = local_patches_dir(project_root)
    dest = dest_dir / f"{stem}.patch"
    if dest.exists() and not force:
        raise PatchError(f"{dest.name} already exists in ./{LOCAL_PATCHES_DIRNAME} (use --force)")
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return PatchEntry(
        id=stem, source=LOCAL, enabled=True, path=dest, header=patches_mod.parse_file(dest)
    )


def remove_local(project_root: Path, token: str) -> PatchEntry:
    """Delete a *local* patch file. Toolkit patches can't be removed (disable
    them instead). Raises :class:`PatchError`."""
    entry = resolve(load(project_root), token)
    if entry.source != LOCAL:
        raise PatchError(
            f"{entry.id} is a toolkit patch — use `disable`, not `rm`"
        )
    entry.path.unlink()
    _prune_disabled_to_known(project_root)
    return entry


def promote(
    project_root: Path,
    token: str,
    *,
    upstream: str | None = None,
    reason: str | None = None,
) -> tuple[Path, str]:
    """Graduate a local patch into the toolkit series (NNNN-<name>.patch).

    Writes into the shipped series with refreshed headers and removes the local
    copy. Must run from a toolkit repo checkout (editable install) — refuses to
    write into an installed package. Returns (new_path, new_id).
    """
    shipped = patches_mod.shipped_patches_dir()
    if "site-packages" in str(shipped):
        raise PatchError(
            "promote writes into the toolkit's patch series — run it from a "
            "toolkit repo checkout (editable install), not an installed package"
        )
    entry = resolve(load(project_root), token)
    if entry.source != LOCAL:
        raise PatchError(f"{entry.id} is already in the toolkit series")

    base = re.sub(r"^\d+-", "", entry.id)  # drop any leading NNNN- from the local id
    n = patches_mod.next_patch_number(shipped)
    dest = shipped / f"{n:04d}-{base}.patch"
    content = patches_mod.inject_headers(
        entry.path.read_text(encoding="utf-8"), upstream=upstream, reason=reason
    )
    dest.write_text(content, encoding="utf-8")
    entry.path.unlink()
    _prune_disabled_to_known(project_root)
    return dest, dest.stem
