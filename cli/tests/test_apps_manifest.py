"""Smoke tests for the apps.yaml round-trip."""

from __future__ import annotations

from pathlib import Path

import yaml

from arches_toolkit import apps_manifest as m
from arches_toolkit.apps_manifest import AppEntry


def test_load_missing_file_returns_empty_manifest(tmp_path: Path) -> None:
    manifest = m.load(tmp_path / "apps.yaml")
    assert manifest.apps == []


def test_load_empty_file_returns_empty_manifest(tmp_path: Path) -> None:
    p = tmp_path / "apps.yaml"
    p.write_text("")
    manifest = m.load(p)
    assert manifest.apps == []


def test_roundtrip_preserves_known_keys(tmp_path: Path) -> None:
    src = tmp_path / "apps.yaml"
    src.write_text(
        yaml.safe_dump(
            {
                "apps": [
                    {
                        "package": "arches-her",
                        "source": "pypi",
                        "version": "~=2.0",
                        "mode": "release",
                    },
                    {
                        "package": "arches-orm",
                        "source": "git",
                        "repo": "https://github.com/flaxandteal/arches-orm.git",
                        "ref": "main",
                        "mode": "develop",
                    },
                ]
            }
        )
    )
    manifest = m.load(src)
    assert [a.package for a in manifest.apps] == ["arches-her", "arches-orm"]

    out = tmp_path / "out.yaml"
    m.save(manifest, out)
    reloaded = m.load(out)
    assert reloaded.to_dict() == manifest.to_dict()


def test_save_is_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "apps.yaml"
    manifest = m.AppsManifest(apps=[AppEntry(package="arches-her", version="~=2.0")])
    m.save(manifest, p)
    mtime1 = p.stat().st_mtime_ns
    m.save(manifest, p)
    mtime2 = p.stat().st_mtime_ns
    assert mtime1 == mtime2  # no rewrite when content unchanged


def test_upsert_adds_then_unchanged_then_updates(tmp_path: Path) -> None:
    manifest = m.AppsManifest()
    action, prev = manifest.upsert(AppEntry(package="arches-her", version="~=2.0"))
    assert action == "added" and prev is None

    action, prev = manifest.upsert(AppEntry(package="arches-her", version="~=2.0"))
    assert action == "unchanged"

    action, prev = manifest.upsert(AppEntry(package="arches-her", version="~=2.1"))
    assert action == "updated"
    assert manifest.find("arches-her").version == "~=2.1"
    assert len(manifest.apps) == 1


def test_unknown_keys_preserved(tmp_path: Path) -> None:
    src = tmp_path / "apps.yaml"
    src.write_text(
        yaml.safe_dump(
            {
                "apps": [
                    {
                        "package": "arches-her",
                        "mode": "release",
                        "wibble": "kept",
                    }
                ],
                "top_level_extra": {"foo": 1},
            }
        )
    )
    manifest = m.load(src)
    assert manifest.apps[0].extras == {"wibble": "kept"}
    assert manifest.extras == {"top_level_extra": {"foo": 1}}

    out = tmp_path / "out.yaml"
    m.save(manifest, out)
    reloaded = yaml.safe_load(out.read_text())
    assert reloaded["apps"][0]["wibble"] == "kept"
    assert reloaded["top_level_extra"] == {"foo": 1}
