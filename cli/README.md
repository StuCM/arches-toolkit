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

## Usage

All commands are run from the **project root** (the directory containing
`apps.yaml` and/or `compose.yaml`), with the exception of the `patch`
subcommands which are run from the **toolkit repo root** (the directory
containing `docker/base/patches/`).

### Add an Arches application

```bash
# Release-mode pypi dep
arches-toolkit add-app arches-her --version "~=2.0"

# Develop-mode git checkout (bind-mounted, editable install)
arches-toolkit add-app arches-orm \
    --source git \
    --repo https://github.com/flaxandteal/arches-orm.git \
    --ref main \
    --mode develop
```

Re-running with the same arguments is a no-op; re-running with different
fields updates the existing entry rather than appending a duplicate.

### Apply manifest changes

```bash
arches-toolkit sync-apps
```

Rewrites `[project.dependencies]` in `pyproject.toml` for `mode: release`
entries (tracked under `[tool.arches-toolkit] managed_apps`) and regenerates
`compose.apps.yaml` for `mode: develop` entries.

### Run the dev stack

```bash
arches-toolkit dev               # docker compose up --watch with overlays
arches-toolkit dev --build       # rebuild images first
arches-toolkit dev -- --no-attach  # extra flags pass through
arches-toolkit dev --dry-run     # print the docker compose invocation only
```

Auto-discovers `compose.yaml`, `compose.dev.yaml`, `compose.apps.yaml`, and
`compose.extras.yaml` (only files that exist are passed with `-f`).

### Patch series (toolkit repo)

```bash
arches-toolkit patch list                     # tabulate patches with metadata
arches-toolkit patch renew 0001-foo.patch     # bump Last-reviewed: to today
GH_TOKEN=... arches-toolkit patch status      # add upstream PR state column
```

`patch status` falls back gracefully if no `GH_TOKEN`/`GITHUB_TOKEN` is set
(prints a warning and skips the API calls).

## Development

```bash
cd cli
uv pip install -e ".[dev]"
pytest
```

## See also

- [../PLAN.md](../PLAN.md)
- [../TASKS.md#stage-5--cli-minimum-viable](../TASKS.md)
