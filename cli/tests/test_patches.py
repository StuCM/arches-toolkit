"""Smoke tests for the patch header parser."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from arches_toolkit import patches as p
from arches_toolkit.patches import PatchHeaderError

SAMPLE_PATCH = """From abc123 Mon Sep 17 00:00:00 2001
From: Test User <test@example.com>
Date: Tue, 1 Apr 2025 12:00:00 +0000
Subject: [PATCH] make frontend_configuration path configurable

Allow ARCHES_FRONTEND_CONFIGURATION_DIR to override the hardcoded path.

Upstream: https://github.com/archesproject/arches/pull/12345
Last-reviewed: 2025-04-01
Reason: enables non-root containers and read-only root filesystems

---
 arches/apps.py | 4 ++++
 1 file changed, 4 insertions(+)

diff --git a/arches/apps.py b/arches/apps.py
index abc..def 100644
--- a/arches/apps.py
+++ b/arches/apps.py
@@ -1,3 +1,7 @@
+import os
+
+# Last-reviewed: 1999-01-01  -- this should NOT be picked up
 class ArchesAppConfig:
     pass
"""


def test_parse_text_extracts_all_headers() -> None:
    h = p.parse_text(SAMPLE_PATCH)
    assert h.subject == "make frontend_configuration path configurable"
    assert h.upstream == "https://github.com/archesproject/arches/pull/12345"
    assert h.last_reviewed == date(2025, 4, 1)
    assert h.reason == "enables non-root containers and read-only root filesystems"
    assert h.upstream_pr == ("archesproject", "arches", 12345)


def test_parse_text_ignores_diff_region() -> None:
    h = p.parse_text(SAMPLE_PATCH)
    # Date in diff body should be ignored.
    assert h.last_reviewed == date(2025, 4, 1)


def test_renew_last_reviewed_rewrites_header(tmp_path: Path) -> None:
    target = tmp_path / "0001-foo.patch"
    target.write_text(SAMPLE_PATCH)
    p.renew_last_reviewed(target, today=date(2026, 4, 14))
    h = p.parse_file(target)
    assert h.last_reviewed == date(2026, 4, 14)
    # Diff region untouched.
    assert "1999-01-01" in target.read_text()


def test_renew_raises_when_header_absent(tmp_path: Path) -> None:
    target = tmp_path / "no-header.patch"
    target.write_text("Subject: [PATCH] no metadata\n\nbody\n---\n")
    with pytest.raises(PatchHeaderError):
        p.renew_last_reviewed(target)


def test_discover_empty_dir(tmp_path: Path) -> None:
    assert p.discover(tmp_path) == []
    assert p.discover(tmp_path / "does-not-exist") == []


def test_discover_returns_sorted(tmp_path: Path) -> None:
    (tmp_path / "0002-b.patch").write_text(SAMPLE_PATCH)
    (tmp_path / "0001-a.patch").write_text(SAMPLE_PATCH)
    (tmp_path / "not-a-patch.txt").write_text("ignored")
    files = p.discover(tmp_path)
    assert [f.name for f in files] == ["0001-a.patch", "0002-b.patch"]


def test_parse_handles_missing_optional_headers() -> None:
    text = (
        "From abc Mon Sep 17 00:00:00 2001\n"
        "Subject: [PATCH] minimal\n\nbody\n---\n"
    )
    h = p.parse_text(text)
    assert h.subject == "minimal"
    assert h.upstream is None
    assert h.last_reviewed is None
    assert h.reason is None
    assert h.days_since_review is None
    assert h.upstream_pr is None
