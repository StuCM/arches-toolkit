"""Parser for ``docker/base/patches/*.patch`` headers.

Patch files are ``git format-patch`` output. The trailing block of the commit
message (between ``Subject:`` and the first ``---`` line) carries three
required headers:

::

    Upstream: <URL or "none yet">
    Last-reviewed: YYYY-MM-DD
    Reason: <one-line justification>

This module is the single source of truth for parsing/rewriting that block.
It is also runnable as ``python -m arches_toolkit.patches dump-json`` so CI
workflows can consume the data without importing typer/rich.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

PATCHES_RELDIR = Path("docker/base/patches")

# Header field regexes — anchored to line start, case-insensitive on the key.
_HEADER_RE = {
    "upstream": re.compile(r"^Upstream:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    "last_reviewed": re.compile(r"^Last-reviewed:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE),
    "reason": re.compile(r"^Reason:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
}

_SUBJECT_RE = re.compile(r"^Subject:\s*(?:\[PATCH[^\]]*\]\s*)?(.*?)$", re.MULTILINE)
_GH_PR_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<num>\d+)/?$"
)


@dataclass
class PatchHeader:
    path: Path
    subject: str
    upstream: str | None
    last_reviewed: date | None
    reason: str | None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def days_since_review(self) -> int | None:
        if self.last_reviewed is None:
            return None
        return (date.today() - self.last_reviewed).days

    @property
    def upstream_pr(self) -> tuple[str, str, int] | None:
        """Parse ``upstream`` as a GitHub PR URL, if it is one."""
        if not self.upstream:
            return None
        m = _GH_PR_RE.match(self.upstream.strip())
        if not m:
            return None
        return m["owner"], m["repo"], int(m["num"])

    def to_dict(self) -> dict:
        d = asdict(self)
        d["path"] = str(self.path)
        d["last_reviewed"] = self.last_reviewed.isoformat() if self.last_reviewed else None
        d["days_since_review"] = self.days_since_review
        return d


class PatchHeaderError(ValueError):
    """Raised when a patch file is missing required header fields."""


def _commit_message_region(text: str) -> str:
    """Slice the patch text to just the commit-message body.

    ``git format-patch`` output ends the commit message with a line ``---``
    that separates message from diffstat/diff. We strip everything from that
    line onward to avoid matching headers that might coincidentally appear in
    the diff context.
    """
    # First ``\n---\n`` (often ``\n---\n diffstat``) ends the message.
    m = re.search(r"^---\s*$", text, re.MULTILINE)
    if m:
        return text[: m.start()]
    return text


def parse_text(text: str, path: Path | None = None) -> PatchHeader:
    region = _commit_message_region(text)

    subject_m = _SUBJECT_RE.search(region)
    subject = subject_m.group(1).strip() if subject_m else ""

    upstream_m = _HEADER_RE["upstream"].search(region)
    last_m = _HEADER_RE["last_reviewed"].search(region)
    reason_m = _HEADER_RE["reason"].search(region)

    last_reviewed: date | None = None
    if last_m:
        try:
            last_reviewed = datetime.strptime(last_m.group(1), "%Y-%m-%d").date()
        except ValueError:
            last_reviewed = None

    return PatchHeader(
        path=path if path is not None else Path("<memory>"),
        subject=subject,
        upstream=upstream_m.group(1) if upstream_m else None,
        last_reviewed=last_reviewed,
        reason=reason_m.group(1) if reason_m else None,
    )


def parse_file(path: Path) -> PatchHeader:
    return parse_text(path.read_text(encoding="utf-8"), path=path)


def discover(patches_dir: Path) -> list[Path]:
    if not patches_dir.is_dir():
        return []
    return sorted(p for p in patches_dir.glob("*.patch") if p.is_file())


def parse_all(patches_dir: Path) -> list[PatchHeader]:
    return [parse_file(p) for p in discover(patches_dir)]


def renew_last_reviewed(path: Path, today: date | None = None) -> date:
    """Rewrite the ``Last-reviewed:`` line in ``path`` to today.

    Raises :class:`PatchHeaderError` if the file has no ``Last-reviewed:``
    line in the commit-message region.
    """
    today = today or date.today()
    original = path.read_text(encoding="utf-8")
    region = _commit_message_region(original)
    if not _HEADER_RE["last_reviewed"].search(region):
        raise PatchHeaderError(
            f"{path}: no 'Last-reviewed:' header found in commit message body"
        )
    new_line = f"Last-reviewed: {today.isoformat()}"
    # Substitute only within the region by splitting and rejoining.
    region_new = _HEADER_RE["last_reviewed"].sub(new_line, region, count=1)
    rewritten = region_new + original[len(region) :]
    if rewritten != original:
        path.write_text(rewritten, encoding="utf-8")
    return today


def headers_to_jsonable(headers: Iterable[PatchHeader]) -> list[dict]:
    return [h.to_dict() for h in headers]


def _main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] != "dump-json":
        print("usage: python -m arches_toolkit.patches dump-json [PATCHES_DIR]", file=sys.stderr)
        return 2
    patches_dir = Path(argv[2]) if len(argv) >= 3 else PATCHES_RELDIR
    headers = parse_all(patches_dir)
    json.dump(headers_to_jsonable(headers), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
