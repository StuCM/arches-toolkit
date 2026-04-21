"""Unit tests for :mod:`arches_toolkit.scaffold`."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from arches_toolkit import scaffold


# --------------------------------------------------------------------------- #
# derive_tokens
# --------------------------------------------------------------------------- #


def test_derive_tokens_snake_case_to_pascal_and_camel():
    t = scaffold.derive_tokens("foo_bar_baz")
    assert t["name"] == "foo_bar_baz"
    assert t["NameCamel"] == "FooBarBaz"
    assert t["nameCamel"] == "fooBarBaz"
    assert t["package_dashed"] == "foo-bar-baz"


def test_derive_tokens_generates_uuid4():
    a = scaffold.derive_tokens("x")["uuid"]
    b = scaffold.derive_tokens("x")["uuid"]
    assert a != b
    assert len(a) == 36


def test_derive_tokens_respects_overrides():
    t = scaffold.derive_tokens("thing", package="arches_demo", slug="a-b")
    assert t["package"] == "arches_demo"
    assert t["slug"] == "a-b"


# --------------------------------------------------------------------------- #
# detect_arches_version
# --------------------------------------------------------------------------- #


def test_detect_version_uses_explicit_flag(tmp_path: Path):
    v = scaffold.detect_arches_version(explicit="8.1", project_root=tmp_path)
    assert v == "8.1"


def test_detect_version_falls_back_closest_lower(tmp_path: Path, caplog):
    with caplog.at_level("WARNING"):
        v = scaffold.detect_arches_version(explicit="9.9", project_root=tmp_path)
    # Only 7.6 and 8.1 ship; 9.9 → closest lower is 8.1
    assert v == "8.1"


def test_detect_version_reads_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "demo"
            dependencies = ["arches>=7.6,<8.0", "django"]
            """
        ).strip(),
        encoding="utf-8",
    )
    v = scaffold.detect_arches_version(explicit=None, project_root=tmp_path)
    assert v == "7.6"


def test_detect_version_latest_when_no_signal(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ARCHES_VERSION", raising=False)
    v = scaffold.detect_arches_version(explicit=None, project_root=tmp_path)
    assert v == "8.1"


# --------------------------------------------------------------------------- #
# resolve_target
# --------------------------------------------------------------------------- #


def _fake_project(root: Path, package: str = "mything") -> Path:
    (root / package).mkdir()
    (root / package / "settings.py").write_text("DATABASES = {}\n", encoding="utf-8")
    (root / ".env").write_text(f"PROJECT_PACKAGE={package}\n", encoding="utf-8")
    return root


def _fake_app(root: Path, package: str = "arches_demo") -> Path:
    (root / package).mkdir()
    (root / package / "apps.py").write_text(
        "class Cfg:\n    is_arches_application = True\n", encoding="utf-8"
    )
    return root


def test_resolve_target_project_via_env(tmp_path: Path):
    _fake_project(tmp_path)
    target = scaffold.resolve_target(cwd=tmp_path, app_dir=None, arches_version="8.1")
    assert target.package == "mything"
    assert target.is_app is False
    assert target.root == tmp_path


def test_resolve_target_project_via_dir_name(tmp_path: Path):
    proj = tmp_path / "acme"
    proj.mkdir()
    (proj / "acme").mkdir()
    (proj / "acme" / "settings.py").write_text("", encoding="utf-8")
    target = scaffold.resolve_target(cwd=proj, app_dir=None, arches_version="8.1")
    assert target.package == "acme"


def test_resolve_target_app(tmp_path: Path):
    _fake_app(tmp_path)
    target = scaffold.resolve_target(
        cwd=tmp_path, app_dir=tmp_path, arches_version="8.1"
    )
    assert target.is_app is True
    assert target.package == "arches_demo"


def test_resolve_target_errors_on_bare_dir(tmp_path: Path):
    with pytest.raises(ValueError, match="not a project"):
        scaffold.resolve_target(cwd=tmp_path, app_dir=None, arches_version="8.1")


def test_resolve_target_errors_on_non_app_dir(tmp_path: Path):
    with pytest.raises(ValueError, match="not an Arches application"):
        scaffold.resolve_target(cwd=tmp_path, app_dir=tmp_path, arches_version="8.1")


# --------------------------------------------------------------------------- #
# render_and_write
# --------------------------------------------------------------------------- #


def test_render_widget_8_1(tmp_path: Path):
    template = scaffold.template_root("8.1", "widget")
    tokens = scaffold.derive_tokens("my_widget", package="mything")
    written = scaffold.render_and_write(template, tmp_path, tokens, force=False)

    json_out = tmp_path / "widgets" / "my_widget.json"
    vue_out = tmp_path / "src" / "mything" / "components" / "widgets" / "MyWidgetWidget.vue"
    assert json_out in written
    assert vue_out in written

    body = json_out.read_text(encoding="utf-8")
    assert '"name": "my_widget"' in body
    assert '"widgetid"' in body
    assert "${" not in body  # no un-substituted placeholders


def test_render_refuses_overwrite_without_force(tmp_path: Path):
    template = scaffold.template_root("8.1", "widget")
    tokens = scaffold.derive_tokens("w", package="mything")
    scaffold.render_and_write(template, tmp_path, tokens, force=False)
    with pytest.raises(FileExistsError):
        scaffold.render_and_write(template, tmp_path, tokens, force=False)


def test_render_force_overwrites(tmp_path: Path):
    template = scaffold.template_root("8.1", "widget")
    tokens = scaffold.derive_tokens("w", package="mything")
    scaffold.render_and_write(template, tmp_path, tokens, force=False)
    # second call with force should not raise
    scaffold.render_and_write(template, tmp_path, tokens, force=True)


def test_render_app_kind_produces_pyproject(tmp_path: Path):
    template = scaffold.template_root("8.1", "app")
    tokens = scaffold.derive_tokens("demo", package="arches_demo")
    scaffold.render_and_write(template, tmp_path, tokens, force=False)
    py = tmp_path / "pyproject.toml"
    assert py.exists()
    assert 'name = "arches-demo"' in py.read_text(encoding="utf-8")
    # Knockout shims don't apply to apps; check the package dir materialised.
    assert (tmp_path / "arches_demo" / "apps.py").exists()
