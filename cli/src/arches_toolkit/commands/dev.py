"""``arches-toolkit dev`` — start the dev stack and watch for file changes.

Baseline compose files and the project Dockerfile ship as CLI package data.
The project directory only needs an optional project-specific
`compose.extras.yaml` for extra services.

Default flow: ``docker compose up -d`` with compose's own progress display
silenced, a readiness poll printing one milestone per startup phase, then
``docker compose watch --no-up`` in the foreground for file syncing. Ctrl-C
stops the watcher only — the stack keeps running (``arches-toolkit down``
stops it). ``--verbose`` reverts to a fully attached ``up --watch`` with the
complete log stream.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from importlib import resources
from pathlib import Path

import typer

from .. import _output

PACKAGE_DATA = "arches_toolkit._data"
BASELINE = ("compose.yaml", "compose.dev.yaml")
PROJECT_OVERLAYS = ("compose.extras.yaml",)
ARCHES_SRC_OVERLAY = "compose.arches-src.yaml"

INFRA_SERVICES = ("db", "elasticsearch", "rabbitmq")

# Ordered startup milestones: (key, message printed when the phase completes).
READY_STAGES = (
    ("infra", "Infrastructure ready (db, elasticsearch, rabbitmq)"),
    ("init", "Setup complete (migrations, static files, search indexes)"),
    ("webpack", "Frontend compiled (webpack)"),
    ("web", "Arches running — http://localhost:8000"),
)

READY_TIMEOUT_SECONDS = 900
POLL_INTERVAL_SECONDS = 2
WAITING_NOTE_EVERY_SECONDS = 30


def _package_data_path(name: str) -> Path:
    p = Path(str(resources.files(PACKAGE_DATA).joinpath(name)))
    if not p.exists():
        raise typer.BadParameter(f"package data missing: {name}")
    return p


def _env_file_var(env_path: Path, key: str) -> str | None:
    """Minimal .env reader — returns the value for key, or None.

    Docker compose reads .env automatically for YAML interpolation, but the
    Python CLI doesn't get that for free. We look up specific keys that gate
    CLI-level behaviour (right now: ARCHES_SRC).
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


def _compose_base(project_root: Path, compose_files: list[Path]) -> list[str]:
    argv = ["docker", "compose", "--project-directory", str(project_root)]
    for f in compose_files:
        argv += ["-f", str(f)]
    return argv


def _up_argv(
    project_root: Path,
    compose_files: list[Path],
    extra: list[str],
    *,
    build: bool,
) -> list[str]:
    argv = _compose_base(project_root, compose_files)
    if _output.is_verbose():
        argv += ["up", "--watch"]
    else:
        # --progress quiet: our readiness milestones are the narrative;
        # compose's own progress tree would duplicate them.
        argv.insert(2, "--progress")
        argv.insert(3, "quiet")
        argv += ["up", "-d"]
    if build:
        argv.append("--build")
    argv += list(extra)
    return argv


def _ps_status(base_argv: list[str], env: dict[str, str]) -> dict[str, dict]:
    """Service name → its `compose ps` record (State / Health / ExitCode)."""
    result = subprocess.run(
        base_argv + ["ps", "-a", "--format", "json"],
        capture_output=True, text=True, env=env,
    )
    services: dict[str, dict] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        name = item.get("Service")
        if name:
            services[name] = item
    return services


def _stage_states(services: dict[str, dict]) -> tuple[dict[str, bool], list[str]]:
    """Evaluate startup milestones from a `compose ps` snapshot.

    Returns (stage key → complete?, failed service names). Pure — unit-tested
    without docker.
    """
    def field(name: str, key: str):
        return (services.get(name) or {}).get(key)

    failures = [
        name for name in (*INFRA_SERVICES, "webpack")
        if field(name, "Health") == "unhealthy"
    ]
    if field("init", "State") == "exited" and field("init", "ExitCode") not in (0, None):
        failures.append("init")

    stages = {
        "infra": all(field(n, "Health") == "healthy" for n in INFRA_SERVICES),
        "init": field("init", "State") == "exited" and field("init", "ExitCode") == 0,
        "webpack": field("webpack", "Health") == "healthy",
        "web": field("web", "State") == "running",
    }
    return stages, failures


def _format_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def _wait_until_ready(
    base_argv: list[str],
    env: dict[str, str],
    up_proc: subprocess.Popen,
) -> None:
    """Poll service states, printing one line per completed milestone."""
    started = time.monotonic()
    done: set[str] = set()
    last_note = 0.0
    while True:
        elapsed = time.monotonic() - started
        services = _ps_status(base_argv, env)
        stages, failures = _stage_states(services)

        for key, message in READY_STAGES:
            if key not in done and stages.get(key):
                done.add(key)
                typer.echo(f"  ✓ {message}  [{_format_elapsed(elapsed)}]")

        if failures:
            up_proc.terminate()
            names = ", ".join(sorted(set(failures)))
            typer.echo(f"  ✗ {names} failed — see: arches-toolkit logs {names.split(',')[0]}", err=True)
            raise typer.Exit(1)

        if len(done) == len(READY_STAGES):
            up_proc.wait()
            return

        rc = up_proc.poll()
        if rc is not None and rc != 0:
            typer.echo(
                "  ✗ docker compose up failed — re-run with `arches-toolkit -v dev` "
                "for the full stream",
                err=True,
            )
            raise typer.Exit(rc)

        if elapsed - last_note >= WAITING_NOTE_EVERY_SECONDS:
            last_note = elapsed
            pending = next((m for k, m in READY_STAGES if k not in done), "")
            if elapsed >= WAITING_NOTE_EVERY_SECONDS:
                typer.echo(f"  … waiting: {pending}  [{_format_elapsed(elapsed)}]")

        if elapsed > READY_TIMEOUT_SECONDS:
            typer.echo(
                f"  ✗ stack not ready after {_format_elapsed(elapsed)} — "
                "inspect with `arches-toolkit ps` / `arches-toolkit logs <service>`",
                err=True,
            )
            raise typer.Exit(1)

        time.sleep(POLL_INTERVAL_SECONDS)


def dev(
    ctx: typer.Context,
    build: bool = typer.Option(False, "--build", help="Force rebuild before bringing up"),
    project_root: Path = typer.Option(
        Path("."),
        "--project-root",
        help="Project root (default: cwd)",
        show_default=False,
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print the docker compose invocation without executing"
    ),
) -> None:
    """Start the dev stack (detached + readiness milestones + file watch)."""
    if shutil.which("docker") is None:
        raise typer.BadParameter("docker not found on PATH")

    dockerfile = _package_data_path("Dockerfile")
    compose_files = [_package_data_path(name) for name in BASELINE]

    project_root = project_root.resolve()
    compose_files += [project_root / n for n in PROJECT_OVERLAYS if (project_root / n).exists()]

    # Shell env wins; fall back to project .env so users can put ARCHES_SRC
    # there alongside other toolkit config.
    arches_src = os.environ.get("ARCHES_SRC") or _env_file_var(
        project_root / ".env", "ARCHES_SRC"
    )
    if arches_src:
        compose_files.append(_package_data_path(ARCHES_SRC_OVERLAY))
        typer.echo(f"ARCHES_SRC={arches_src}  (overlay: compose.arches-src.yaml)")

    argv = _up_argv(project_root, compose_files, list(ctx.args), build=build)
    env = os.environ.copy()
    env["ARCHES_TOOLKIT_DOCKERFILE"] = str(dockerfile)
    # Make ARCHES_SRC available to compose even if it came from .env only.
    if arches_src:
        env["ARCHES_SRC"] = arches_src

    if dry_run:
        # --dry-run's whole purpose is showing the invocation — always print.
        typer.echo(f"ARCHES_TOOLKIT_DOCKERFILE={dockerfile}")
        typer.echo(" ".join(argv))
        return

    if _output.is_verbose():
        _output.stage("Starting the dev stack (docker compose up --watch, full logs)")
        _output.cmd(f"ARCHES_TOOLKIT_DOCKERFILE={dockerfile}")
        _output.cmd(argv)
        completed = subprocess.run(argv, env=env)
        raise typer.Exit(completed.returncode)

    base_argv = _compose_base(project_root, compose_files)
    _output.stage("Starting the dev stack")
    up_proc = subprocess.Popen(argv, env=env)
    try:
        _wait_until_ready(base_argv, env, up_proc)
    except KeyboardInterrupt:
        typer.echo(
            "\nInterrupted — the stack may still be starting in the background. "
            "`arches-toolkit ps` to check, `arches-toolkit down` to stop."
        )
        raise typer.Exit(130)

    _output.stage(
        "Watching for file changes — Ctrl-C stops watching; "
        "`arches-toolkit down` stops the stack"
    )
    try:
        subprocess.run(base_argv + ["watch", "--no-up"], env=env)
    except KeyboardInterrupt:
        pass
    typer.echo(
        "\nStopped watching. The stack is still running — "
        "`arches-toolkit down` to stop it."
    )
