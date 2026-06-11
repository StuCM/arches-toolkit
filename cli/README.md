# arches-toolkit CLI

Python package providing the `arches-toolkit` command. End-user docs live in the top-level [../README.md](../README.md); this file is for people working on the CLI itself.

## Commands

| Command | Purpose |
|---|---|
| `arches-toolkit init <name>` | Scaffold a new Arches project |
| `arches-toolkit migrate` | Convert an existing project to arches-toolkit shape (`--dual-mode` to keep legacy CI) |
| `arches-toolkit setup-db` | **Destructive, one-time**: drop+rebuild DB, ES indexes, system settings |
| `arches-toolkit add-app <pkg>` | Add an Arches application to `apps.yaml` |
| `arches-toolkit sync-apps` | Apply `apps.yaml` changes to `pyproject.toml` + INSTALLED_APPS |
| `arches-toolkit create <kind> <name>` | Scaffold widget / plugin / component / app / etc. — see [../docs/create.md](../docs/create.md) |
| `arches-toolkit dev [--build] [--dry-run]` | `docker compose up --watch` with auto-discovered overlays |
| `arches-toolkit build` | `docker compose build` (no start) |
| `arches-toolkit logs [-f] [service]` | `docker compose logs` wrapper |
| `arches-toolkit ps` | `docker compose ps` wrapper |
| `arches-toolkit exec <service> <cmd…>` | `docker compose exec` wrapper |
| `arches-toolkit restart [service…]` | `docker compose restart` wrapper |
| `arches-toolkit down [-v]` | Stop containers (`-v` wipes volumes) |
| `arches-toolkit manage <cmd…>` | Run `python manage.py <cmd…>` inside the web container |
| `arches-toolkit patch start/finish/list/renew/status` | Maintain the Arches patch series |

All commands are run from the **project root** (the directory containing `.env` / `apps.yaml`), with the exception of the `patch` subcommands, which are run from the **toolkit repo root** (the directory containing `docker/base/patches/`).

Full command reference with flags: `arches-toolkit <command> --help`.

## Distribution

- Target: publish to PyPI as `arches-toolkit`. Pending.
- Today: `uv tool install -e ./cli` from a local checkout.
- Once on PyPI: `uvx arches-toolkit <command>` (no permanent install), or `uv tool install arches-toolkit` / `pipx install arches-toolkit`.

## Development

```bash
cd cli
uv pip install -e ".[dev]"
pytest
```

The CLI ships compose files, the project Dockerfile, and `init.sql` as package data under `src/arches_toolkit/_data/`. Changes there are picked up by an editable install without reinstalling.

## See also

- [../README.md](../README.md) — end-user docs
- [../PLAN.md](../PLAN.md) — design rationale
- [../docs/create.md](../docs/create.md) — `create` subcommand reference
