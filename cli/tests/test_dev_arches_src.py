"""Tests for the ARCHES_SRC overlay wiring in ``arches-toolkit dev``.

These are unit tests, not integration tests — they verify that the CLI
decides to include ``compose.arches-src.yaml`` in the right circumstances
and exports ARCHES_SRC to the compose subprocess. They do not start Docker.

The full end-to-end mount check (does Python actually import from /opt/arches
at runtime?) requires a live container; see ``docs/local-arches-src.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from arches_toolkit import main as main_module
from arches_toolkit.commands import dev as dev_module


OVERLAY_NAME = "compose.arches-src.yaml"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A minimal project directory: has a .env so _require_project passes."""
    (tmp_path / ".env").write_text("PROJECT_NAME=test\n", encoding="utf-8")
    return tmp_path


# --------------------------------------------------------------------------- #
# _env_file_var — minimal .env reader
# --------------------------------------------------------------------------- #


def test_env_file_var_returns_value(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("FOO=bar\nARCHES_SRC=/home/x/arches\n", encoding="utf-8")
    assert dev_module._env_file_var(env, "ARCHES_SRC") == "/home/x/arches"
    assert dev_module._env_file_var(env, "FOO") == "bar"


def test_env_file_var_missing_key_returns_none(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("FOO=bar\n", encoding="utf-8")
    assert dev_module._env_file_var(env, "ARCHES_SRC") is None


def test_env_file_var_missing_file_returns_none(tmp_path: Path):
    assert dev_module._env_file_var(tmp_path / ".env", "ARCHES_SRC") is None


def test_env_file_var_strips_quotes_and_whitespace(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text('ARCHES_SRC=  "/quoted/path"  \n', encoding="utf-8")
    assert dev_module._env_file_var(env, "ARCHES_SRC") == "/quoted/path"


def test_env_file_var_ignores_comments_and_blank_lines(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n\nARCHES_SRC=/p\n# trailing comment\n", encoding="utf-8"
    )
    assert dev_module._env_file_var(env, "ARCHES_SRC") == "/p"


# --------------------------------------------------------------------------- #
# dev command — overlay inclusion based on ARCHES_SRC source
# --------------------------------------------------------------------------- #


def test_dev_no_arches_src_no_overlay(runner: CliRunner, project_dir: Path, monkeypatch):
    """With ARCHES_SRC unset and absent from .env, the overlay is not added."""
    monkeypatch.delenv("ARCHES_SRC", raising=False)
    result = runner.invoke(
        main_module.app,
        ["dev", "--project-root", str(project_dir), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert OVERLAY_NAME not in result.output
    assert "ARCHES_SRC=" not in result.output


def test_dev_default_is_detached_and_quiet(
    runner: CliRunner, project_dir: Path, monkeypatch
):
    """Minimal default: detached up with compose's progress display silenced —
    the CLI's own readiness milestones are the narrative."""
    monkeypatch.delenv("ARCHES_SRC", raising=False)
    result = runner.invoke(
        main_module.app,
        ["dev", "--project-root", str(project_dir), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "up -d" in result.output
    assert "--progress quiet" in result.output
    assert "--watch" not in result.output


def test_dev_verbose_is_attached_watch(
    runner: CliRunner, project_dir: Path, monkeypatch
):
    """--verbose reverts to fully attached `up --watch` with all logs."""
    monkeypatch.delenv("ARCHES_SRC", raising=False)
    result = runner.invoke(
        main_module.app,
        ["-v", "dev", "--project-root", str(project_dir), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "up --watch" in result.output
    assert "--progress quiet" not in result.output


# --------------------------------------------------------------------------- #
# readiness milestone evaluation (pure logic)
# --------------------------------------------------------------------------- #

from arches_toolkit.commands.dev import _stage_states  # noqa: E402


def _svc(state="running", health="", exit_code=None):
    item = {"State": state, "Health": health}
    if exit_code is not None:
        item["ExitCode"] = exit_code
    return item


def test_stage_states_all_ready():
    services = {
        "db": _svc(health="healthy"),
        "elasticsearch": _svc(health="healthy"),
        "rabbitmq": _svc(health="healthy"),
        "init": _svc(state="exited", exit_code=0),
        "webpack": _svc(health="healthy"),
        "web": _svc(state="running"),
    }
    stages, failures = _stage_states(services)
    assert all(stages.values())
    assert failures == []


def test_stage_states_cold_start_progression():
    """Mid-cold-start: infra healthy, init still running, nothing downstream."""
    services = {
        "db": _svc(health="healthy"),
        "elasticsearch": _svc(health="healthy"),
        "rabbitmq": _svc(health="healthy"),
        "init": _svc(state="running"),
    }
    stages, failures = _stage_states(services)
    assert stages["infra"] is True
    assert stages["init"] is False
    assert stages["webpack"] is False
    assert stages["web"] is False
    assert failures == []


def test_stage_states_init_failure_detected():
    services = {
        "db": _svc(health="healthy"),
        "elasticsearch": _svc(health="healthy"),
        "rabbitmq": _svc(health="healthy"),
        "init": _svc(state="exited", exit_code=1),
    }
    _, failures = _stage_states(services)
    assert "init" in failures


def test_stage_states_unhealthy_infra_detected():
    services = {"db": _svc(health="unhealthy")}
    _, failures = _stage_states(services)
    assert "db" in failures


def test_dev_shell_env_adds_overlay(
    runner: CliRunner, project_dir: Path, monkeypatch
):
    """ARCHES_SRC set in shell env triggers the overlay."""
    monkeypatch.setenv("ARCHES_SRC", "/opt/my-arches-clone")
    result = runner.invoke(
        main_module.app,
        ["dev", "--project-root", str(project_dir), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert OVERLAY_NAME in result.output
    assert "ARCHES_SRC=/opt/my-arches-clone" in result.output


def test_dev_dotenv_only_adds_overlay(
    runner: CliRunner, project_dir: Path, monkeypatch
):
    """ARCHES_SRC only in .env still triggers the overlay (fallback path)."""
    monkeypatch.delenv("ARCHES_SRC", raising=False)
    (project_dir / ".env").write_text(
        "PROJECT_NAME=test\nARCHES_SRC=/home/dev/arches\n", encoding="utf-8"
    )
    result = runner.invoke(
        main_module.app,
        ["dev", "--project-root", str(project_dir), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert OVERLAY_NAME in result.output
    assert "ARCHES_SRC=/home/dev/arches" in result.output


def test_dev_shell_overrides_dotenv(
    runner: CliRunner, project_dir: Path, monkeypatch
):
    """When both shell and .env set ARCHES_SRC, shell wins (Unix precedence)."""
    monkeypatch.setenv("ARCHES_SRC", "/from/shell")
    (project_dir / ".env").write_text(
        "PROJECT_NAME=test\nARCHES_SRC=/from/dotenv\n", encoding="utf-8"
    )
    result = runner.invoke(
        main_module.app,
        ["dev", "--project-root", str(project_dir), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "ARCHES_SRC=/from/shell" in result.output
    assert "ARCHES_SRC=/from/dotenv" not in result.output


# --------------------------------------------------------------------------- #
# Overlay file shape — catches regressions in the shipped package data
# --------------------------------------------------------------------------- #


def test_overlay_file_mounts_arches_src_over_opt_arches_on_all_services():
    """Regression guard: the shipped overlay bind-mounts ${ARCHES_SRC} onto
    /opt/arches — the location the base image installs Arches editable from.
    Python imports (via the editable .pth) resolve to /opt/arches, so
    mounting over it means clone edits are live. Applies to
    init/web/worker/api/webpack."""
    overlay = dev_module._package_data_path(OVERLAY_NAME)
    text = overlay.read_text(encoding="utf-8")
    assert "${ARCHES_SRC}:/opt/arches" in text, (
        "overlay no longer bind-mounts ARCHES_SRC onto /opt/arches — this is "
        "the location the editable install points at; without this mount, "
        "clone edits don't reach Python imports"
    )
    for svc in ("init", "web", "worker", "api", "webpack"):
        assert f"{svc}:" in text, (
            f"overlay is missing the '{svc}' service — without it, that "
            f"service won't see your Arches clone and imports/bundles will "
            f"diverge from the others"
        )


# --------------------------------------------------------------------------- #
# No runtime install magic — uv sync at build time is authoritative
# --------------------------------------------------------------------------- #


def test_project_dockerfile_does_not_force_reinstall_arches_unconditionally():
    """Regression guard against clobbering uv sync's arches at build time.
    An earlier design force-installed arches editable from /opt/arches after
    uv sync, which silently clobbered the project's locked arches version
    and caused API skew (e.g. missing VERSION attribute). Don't reintroduce.
    """
    dockerfile = dev_module._package_data_path("Dockerfile")
    text = dockerfile.read_text(encoding="utf-8")
    bad_patterns = (
        "--force-reinstall --no-deps -e /opt/arches",
        "--force-reinstall -e /opt/arches",
    )
    for pattern in bad_patterns:
        assert pattern not in text, (
            f"project Dockerfile contains `{pattern}` at build time — this "
            "clobbers the project's uv.lock-installed arches with whatever "
            "is baked into the base image. Use the ARCHES_SRC overlay "
            "(site-packages bind mount) for live-editing instead."
        )


def test_init_service_has_no_runtime_opt_apps_install_loop():
    """Regression guard against the old install-at-runtime design.
    The init service should not be iterating /opt/apps and running uv pip
    install on develop-mode apps — that's handled by uv sync at image
    build time (the app is a normal pyproject dep). The bind-mount overlay
    handles live source editing."""
    compose_dev = dev_module._package_data_path("compose.dev.yaml")
    text = compose_dev.read_text(encoding="utf-8")
    assert "/opt/apps/*/" not in text, (
        "init service appears to still iterate /opt/apps/*/ — that pattern "
        "belongs to the old install-at-runtime design and should be gone. "
        "Develop-mode apps are installed at image build time via uv sync."
    )
    assert "uv pip install" not in text or "--force-reinstall -e" not in text, (
        "init service appears to run force-reinstall editable installs at "
        "runtime — that's the old design and creates version-skew bugs. "
        "uv sync at image build time is authoritative."
    )
