# arches-toolkit CLI

Python package providing the `arches-toolkit` command.

## Commands (target state)

| Command | Purpose |
|---|---|
| `arches-toolkit add-app <pkg>` | Add an Arches application to `apps.yaml` |
| `arches-toolkit sync-apps` | Apply `apps.yaml` changes to `pyproject.toml` / `compose.apps.yaml` |
| `arches-toolkit dev [flags]` | Run `docker compose up --watch` with auto-discovered overlay files |
| `arches-toolkit patch list` | Show all patches with metadata and upstream status |
| `arches-toolkit patch renew <name>` | Bump `Last-reviewed:` in a patch header |
| `arches-toolkit patch status` | Query GitHub API for upstream PR state of all patches |
| `arches-toolkit init <name>` | (Phase 2) Scaffold a new Arches project |
| `arches-toolkit upgrade` | (Phase 2) Upgrade project to a new toolkit version |

## Distribution

- Published to PyPI as `arches-toolkit`
- Recommended install: `uvx arches-toolkit <command>` (no permanent install needed)
- Also installable via `pipx install arches-toolkit` or `uv tool install arches-toolkit`

## See also

- [../PLAN.md](../PLAN.md)
- [../TASKS.md#stage-5--cli-minimum-viable](../TASKS.md)
