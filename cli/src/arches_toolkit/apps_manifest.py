"""Read/write the project ``apps.yaml`` manifest.

The schema (see PLAN.md) is intentionally permissive: unknown top-level keys
and unknown per-entry keys are preserved verbatim. The writer is idempotent —
calling :func:`save` after :func:`load` round-trips deterministically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

LOG = logging.getLogger(__name__)

KNOWN_ENTRY_KEYS = {"package", "source", "version", "repo", "ref", "mode", "path", "extras"}
VALID_SOURCES = {"pypi", "git"}
VALID_MODES = {"release", "develop"}

DEFAULT_MANIFEST_NAME = "apps.yaml"


@dataclass
class AppEntry:
    package: str
    source: str = "pypi"
    version: str | None = None
    repo: str | None = None
    ref: str | None = None
    mode: str = "release"
    # path: optional override for the sibling directory name used by
    # compose.apps.yaml's bind mount in develop mode. When unset, sync-apps
    # derives the dirname from `repo` (stripping `.git`) or falls back to
    # `package`. Use this when your clone is checked out under a non-default
    # name — e.g. a branch-named dir like `2.0.x/` instead of `arches-her/`.
    path: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"package": self.package, "source": self.source}
        if self.version is not None:
            out["version"] = self.version
        if self.repo is not None:
            out["repo"] = self.repo
        if self.ref is not None:
            out["ref"] = self.ref
        out["mode"] = self.mode
        if self.path is not None:
            out["path"] = self.path
        # Re-attach unknown keys at the end, sorted for determinism.
        for k in sorted(self.extras):
            out[k] = self.extras[k]
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppEntry":
        if "package" not in data:
            raise ValueError("apps.yaml entry missing required 'package' field")
        extras = {k: v for k, v in data.items() if k not in KNOWN_ENTRY_KEYS}
        for k in extras:
            LOG.info("apps.yaml: preserving unknown key %r on package %r", k, data["package"])
        source = data.get("source", "pypi")
        if source not in VALID_SOURCES:
            LOG.warning("apps.yaml: unknown source %r on package %r", source, data["package"])
        mode = data.get("mode", "release")
        if mode not in VALID_MODES:
            LOG.warning("apps.yaml: unknown mode %r on package %r", mode, data["package"])
        return cls(
            package=data["package"],
            source=source,
            version=data.get("version"),
            repo=data.get("repo"),
            ref=data.get("ref"),
            mode=mode,
            path=data.get("path"),
            extras=extras,
        )

    def equivalent(self, other: "AppEntry") -> bool:
        """Field-wise equality for idempotency checks."""
        return self.to_dict() == other.to_dict()


@dataclass
class AppsManifest:
    apps: list[AppEntry] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    def find(self, package: str) -> AppEntry | None:
        for a in self.apps:
            if a.package == package:
                return a
        return None

    def upsert(self, entry: AppEntry) -> tuple[str, AppEntry | None]:
        """Insert or update ``entry``.

        Returns a tuple ``(action, previous)`` where ``action`` is one of
        ``"added"``, ``"updated"`` or ``"unchanged"``.
        """
        existing = self.find(entry.package)
        if existing is None:
            self.apps.append(entry)
            return "added", None
        if existing.equivalent(entry):
            return "unchanged", existing
        # Update in place, preserving position.
        idx = self.apps.index(existing)
        self.apps[idx] = entry
        return "updated", existing

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"apps": [a.to_dict() for a in self.apps]}
        for k in sorted(self.extras):
            out[k] = self.extras[k]
        return out


def load(path: Path) -> AppsManifest:
    if not path.exists():
        return AppsManifest()
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return AppsManifest()
    raw = yaml.safe_load(text)
    if raw is None:
        return AppsManifest()
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level must be a mapping")
    apps_raw = raw.get("apps") or []
    if not isinstance(apps_raw, list):
        raise ValueError(f"{path}: 'apps' must be a list")
    apps = [AppEntry.from_dict(item) for item in apps_raw if isinstance(item, dict)]
    extras = {k: v for k, v in raw.items() if k != "apps"}
    for k in extras:
        LOG.info("apps.yaml: preserving unknown top-level key %r", k)
    return AppsManifest(apps=apps, extras=extras)


def save(manifest: AppsManifest, path: Path) -> None:
    """Idempotent write — safe to call repeatedly."""
    payload = manifest.to_dict()
    text = yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def iter_release(manifest: AppsManifest) -> Iterable[AppEntry]:
    return (a for a in manifest.apps if a.mode == "release")


def iter_develop(manifest: AppsManifest) -> Iterable[AppEntry]:
    return (a for a in manifest.apps if a.mode == "develop")
