"""Tests for ``arches-toolkit sync-apps`` — specifically the bits where
apps.yaml schema choices affect the generated compose.apps.yaml and the
pyproject.toml dep list.
"""

from __future__ import annotations

from pathlib import Path

from arches_toolkit.apps_manifest import AppEntry
from arches_toolkit.commands.sync_apps import (
    INSTALLED_APPS_MARKER_END,
    INSTALLED_APPS_MARKER_START,
    _build_compose_apps,
    _develop_repo_dirname,
    _find_settings_path,
    _python_module_name,
    _release_dep_spec,
    _sync_installed_apps,
)


# --------------------------------------------------------------------------- #
# _develop_repo_dirname precedence
# --------------------------------------------------------------------------- #


def test_develop_dirname_path_wins_over_repo_and_package():
    """Explicit `path:` on an entry overrides both the repo-derived name
    (normally `arches-her` from the .git URL) and the package fallback.

    This is the fix for the 'clone is checked out under a branch-named
    directory' case — e.g. an arches-her clone sitting in `../2.0.x/`.
    """
    entry = AppEntry(
        package="arches-her",
        source="git",
        repo="https://github.com/archesproject/arches-her.git",
        ref="dev/2.0.x",
        mode="develop",
        path="2.0.x",
    )
    assert _develop_repo_dirname(entry) == "2.0.x"


def test_develop_dirname_repo_used_when_no_path():
    entry = AppEntry(
        package="arches-her",
        source="git",
        repo="https://github.com/archesproject/arches-her.git",
        mode="develop",
    )
    assert _develop_repo_dirname(entry) == "arches-her"


def test_develop_dirname_repo_strips_trailing_git():
    entry = AppEntry(
        package="arches-her",
        source="git",
        repo="https://github.com/x/arches-her.git/",
        mode="develop",
    )
    assert _develop_repo_dirname(entry) == "arches-her"


def test_develop_dirname_falls_back_to_package():
    entry = AppEntry(package="arches-her", source="pypi", mode="develop")
    assert _develop_repo_dirname(entry) == "arches-her"


# --------------------------------------------------------------------------- #
# _python_module_name — hyphen→underscore conversion for site-packages paths
# --------------------------------------------------------------------------- #


def test_python_module_name_hyphens_to_underscores():
    assert _python_module_name("arches-her") == "arches_her"
    assert _python_module_name("arches-controlled-lists") == "arches_controlled_lists"
    assert _python_module_name("arches-file-upload-3d-extension") == (
        "arches_file_upload_3d_extension"
    )


def test_python_module_name_already_underscore_unchanged():
    assert _python_module_name("arches_her") == "arches_her"


# --------------------------------------------------------------------------- #
# _build_compose_apps — overlay mounts at site-packages
# --------------------------------------------------------------------------- #


def test_build_compose_apps_uses_overlay_mount_with_path_override():
    """develop-mode entry with path override → bind mount at
    /venv/.../site-packages/<python_name> from ../<path>/<python_name>.
    Applies to all services that import app code plus webpack.
    """
    entry = AppEntry(
        package="arches-her",
        source="git",
        repo="https://github.com/archesproject/arches-her.git",
        ref="dev/2.0.x",
        mode="develop",
        path="2.0.x",
    )
    doc = _build_compose_apps([entry])
    mount = "../2.0.x/arches_her:/venv/lib/python3.12/site-packages/arches_her"
    assert doc == {
        "services": {
            "init": {"volumes": [mount]},
            "web": {"volumes": [mount]},
            "worker": {"volumes": [mount]},
            "api": {"volumes": [mount]},
            "webpack": {"volumes": [mount]},
        }
    }


def test_build_compose_apps_uses_package_name_when_no_path():
    """Without an explicit path, both sides of the mount derive from the
    package name (converted from dist → module naming)."""
    entry = AppEntry(package="arches-foo", source="pypi", mode="develop")
    doc = _build_compose_apps([entry])
    mount = "../arches-foo/arches_foo:/venv/lib/python3.12/site-packages/arches_foo"
    assert doc["services"]["web"]["volumes"] == [mount]


def test_build_compose_apps_includes_webpack():
    """Regression guard: webpack MUST get the overlay mount. arches's webpack
    config reads apps' JS from the same site-packages path; without webpack
    in the mount list, the bundler reads the unmodified install and the UI
    won't reflect your clone's edits."""
    entry = AppEntry(package="arches-foo", source="pypi", mode="develop")
    doc = _build_compose_apps([entry])
    assert "webpack" in doc["services"], (
        "webpack missing from compose.apps.yaml — Python services would see "
        "your edits but the bundled JS wouldn't"
    )


# --------------------------------------------------------------------------- #
# _release_dep_spec — unrelated but useful regression surface
# --------------------------------------------------------------------------- #


def test_release_dep_spec_pypi_with_version():
    entry = AppEntry(package="arches-foo", source="pypi", version=">=1.2", mode="release")
    assert _release_dep_spec(entry) == "arches-foo>=1.2"


def test_release_dep_spec_pypi_bare_version_pins_exact():
    entry = AppEntry(package="arches-foo", source="pypi", version="1.2.3", mode="release")
    assert _release_dep_spec(entry) == "arches-foo==1.2.3"


def test_release_dep_spec_git_with_ref():
    entry = AppEntry(
        package="arches-foo",
        source="git",
        repo="https://github.com/x/arches-foo.git",
        ref="v1.2.3",
        mode="release",
    )
    assert _release_dep_spec(entry) == (
        "arches-foo @ git+https://github.com/x/arches-foo.git@v1.2.3"
    )


# --------------------------------------------------------------------------- #
# INSTALLED_APPS auto-management
# --------------------------------------------------------------------------- #


def _make_project_with_settings(
    tmp_path: Path, installed_apps_source: str = ""
) -> Path:
    """Create a minimal project-like dir with .env + <pkg>/settings.py."""
    (tmp_path / ".env").write_text("PROJECT_PACKAGE=testpkg\n", encoding="utf-8")
    pkg = tmp_path / "testpkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "settings.py").write_text(installed_apps_source, encoding="utf-8")
    return tmp_path


def test_find_settings_path_via_env(tmp_path: Path):
    proj = _make_project_with_settings(tmp_path)
    assert _find_settings_path(proj) == proj / "testpkg" / "settings.py"


def test_find_settings_path_fallback_scan(tmp_path: Path):
    # No .env, but a package dir matches
    pkg = tmp_path / "somepkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "settings.py").write_text("INSTALLED_APPS = ()\n", encoding="utf-8")
    assert _find_settings_path(tmp_path) == pkg / "settings.py"


def test_sync_installed_apps_inserts_into_list_literal(tmp_path: Path):
    """If settings.py's INSTALLED_APPS has no toolkit markers yet, sync-apps
    injects them inside the list literal — not as a separate block."""
    proj = _make_project_with_settings(
        tmp_path,
        (
            "INSTALLED_APPS = [\n"
            "    'django.contrib.admin',\n"
            "    'django.contrib.auth',\n"
            "]\n"
        ),
    )
    entries = [
        AppEntry(package="arches-foo", source="pypi", mode="release"),
        AppEntry(
            package="arches-my-new", source="local", mode="develop",
            path="arches-my-new",
        ),
    ]
    status = _sync_installed_apps(entries, proj)
    assert "inserted" in status or "updated" in status

    text = (proj / "testpkg" / "settings.py").read_text(encoding="utf-8")
    # Execute the file and check INSTALLED_APPS is a real list containing
    # both the manual entries and the managed ones — no runtime magic.
    namespace: dict = {}
    exec(text, namespace)
    installed = list(namespace["INSTALLED_APPS"])
    assert "django.contrib.admin" in installed
    assert "django.contrib.auth" in installed
    assert "arches_foo" in installed
    assert "arches_my_new" in installed
    # Managed entries appear inside the original literal, not as a separate block
    assert INSTALLED_APPS_MARKER_START in text
    assert INSTALLED_APPS_MARKER_END in text
    # And no runtime-extension fragment
    assert "_ARCHES_TOOLKIT_APPS" not in text
    assert "except NameError" not in text


def test_sync_installed_apps_inserts_into_tuple_literal(tmp_path: Path):
    """Also works for the tuple form — `INSTALLED_APPS = (...)`."""
    proj = _make_project_with_settings(
        tmp_path,
        (
            "INSTALLED_APPS = (\n"
            "    'django.contrib.admin',\n"
            ")\n"
        ),
    )
    _sync_installed_apps(
        [AppEntry(package="arches-foo", source="pypi", mode="release")],
        proj,
    )
    text = (proj / "testpkg" / "settings.py").read_text(encoding="utf-8")
    namespace: dict = {}
    exec(text, namespace)
    assert "arches_foo" in namespace["INSTALLED_APPS"]


def test_sync_installed_apps_idempotent(tmp_path: Path):
    """Re-running sync-apps with the same inputs produces no diff."""
    proj = _make_project_with_settings(
        tmp_path,
        "INSTALLED_APPS = [\n    'django.contrib.admin',\n]\n",
    )
    entries = [AppEntry(package="arches-foo", source="pypi", mode="release")]
    _sync_installed_apps(entries, proj)
    first = (proj / "testpkg" / "settings.py").read_text(encoding="utf-8")
    status = _sync_installed_apps(entries, proj)
    assert "already in sync" in status
    second = (proj / "testpkg" / "settings.py").read_text(encoding="utf-8")
    assert first == second


def test_sync_installed_apps_removes_apps_removed_from_yaml(tmp_path: Path):
    """Dropping an entry from apps.yaml removes it from the managed section
    on the next run."""
    proj = _make_project_with_settings(
        tmp_path,
        "INSTALLED_APPS = [\n    'django.contrib.admin',\n]\n",
    )
    _sync_installed_apps(
        [
            AppEntry(package="arches-foo", source="pypi", mode="release"),
            AppEntry(package="arches-bar", source="pypi", mode="release"),
        ],
        proj,
    )
    _sync_installed_apps(
        [AppEntry(package="arches-foo", source="pypi", mode="release")],
        proj,
    )
    text = (proj / "testpkg" / "settings.py").read_text(encoding="utf-8")
    namespace: dict = {}
    exec(text, namespace)
    assert "arches_foo" in namespace["INSTALLED_APPS"]
    assert "arches_bar" not in namespace["INSTALLED_APPS"]


def test_sync_installed_apps_preserves_manual_entries(tmp_path: Path):
    """Entries the user added outside the markers must stay untouched, even
    after multiple sync-apps runs."""
    proj = _make_project_with_settings(
        tmp_path,
        (
            "INSTALLED_APPS = [\n"
            "    'django.contrib.admin',\n"
            "    'django.contrib.auth',\n"
            "    'my.custom.app',\n"
            "]\n"
        ),
    )
    _sync_installed_apps(
        [AppEntry(package="arches-foo", source="pypi", mode="release")],
        proj,
    )
    # Also test remove-an-app case preserves manual entries
    _sync_installed_apps([], proj)
    text = (proj / "testpkg" / "settings.py").read_text(encoding="utf-8")
    namespace: dict = {}
    exec(text, namespace)
    for manual in ("django.contrib.admin", "django.contrib.auth", "my.custom.app"):
        assert manual in namespace["INSTALLED_APPS"], (
            f"manual entry {manual!r} was clobbered"
        )


def test_sync_installed_apps_no_installed_apps_assignment(tmp_path: Path):
    """If settings.py doesn't assign INSTALLED_APPS at all (only += or
    complex construction), sync-apps reports and skips rather than guessing."""
    proj = _make_project_with_settings(
        tmp_path,
        "# settings.py has no INSTALLED_APPS at top level\n"
        "some_other = ('foo', 'bar')\n",
    )
    status = _sync_installed_apps(
        [AppEntry(package="arches-foo", source="pypi", mode="release")],
        proj,
    )
    assert "no top-level INSTALLED_APPS" in status
    # settings.py unchanged
    text = (proj / "testpkg" / "settings.py").read_text(encoding="utf-8")
    assert INSTALLED_APPS_MARKER_START not in text


def test_sync_installed_apps_handles_missing_settings_gracefully(tmp_path: Path):
    """If settings.py can't be located, sync-apps reports and skips — no
    crash, no error."""
    status = _sync_installed_apps(
        [AppEntry(package="arches-foo", source="pypi", mode="release")],
        tmp_path,
    )
    assert "not found" in status
