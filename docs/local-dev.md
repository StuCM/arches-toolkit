# Local development with `arches-toolkit`

From `git clone` to a running Arches stack in under ten minutes. No
system-wide Python, no manual virtualenvs, no rebuilding an image every
time a Python dependency changes.

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Docker Engine | 25.0+ (compose v2.24+ for `develop.watch`) | Runs the stack |
| `uv` | 0.4+ | Dependency management — `pipx install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `git` | any modern | Clone the repo |
| Free host ports | `8000`, `8001`, `9000`, `5678`, `5432`, `9200`, `5672`, `15672`, `8182` | See [Troubleshooting](#troubleshooting) if any of these are in use |

Optional: `arches-toolkit` CLI itself, via `uvx arches-toolkit …` — the
examples below show both the CLI form and the underlying
`docker compose` command.

## Quick start

```sh
git clone git@github.com:flaxandteal-arches/<your-project>.git
cd <your-project>
cp .env.example .env        # project-owned; set DJANGO_SETTINGS_MODULE etc.

arches-toolkit dev
# …or, without the CLI:
docker compose \
  -f docker/project/compose.yaml \
  -f docker/project/compose.dev.yaml \
  up --watch
```

On first run:

1. The project image builds against `target: dev`.
2. `db`, `elasticsearch`, `rabbitmq`, `cantaloupe` start and become healthy.
3. The `init` service runs migrations, `collectstatic`, and
   `generate_frontend_configuration`, then exits with status 0.
4. `web`, `worker`, `api` start; `web` is reachable at
   <http://localhost:8000>.

Subsequent runs skip steps 1-3 unless you've changed `pyproject.toml`,
`uv.lock`, or the Dockerfile — the baked venv and migrations are cached
on named volumes.

## The dependency workflow (why this project exists)

### Adding a Python package

```sh
# Edit pyproject.toml — add the package to [project.dependencies].
docker compose exec web uv sync
```

That's it. `uv sync` takes 1-3 seconds on a warm cache, installs into the
`venv` named volume which all three Arches services share, and Django's
autoreload picks up any code path that imports the new package. No
`docker build`, no container restart, no volume nuke.

### Adding an Arches application

```sh
arches-toolkit add-app arches-her --source pypi --version "~=2.0"
arches-toolkit sync-apps                   # rewrites pyproject.toml
docker compose exec web uv sync            # install
# follow the printed one-liner to extend INSTALLED_APPS if needed
```

For apps you're developing in lockstep with the project, use
`--mode develop`; `sync-apps` emits a `compose.apps.yaml` that bind-mounts
your working copy and does an editable install. Details in
[../PLAN.md](../PLAN.md) §Applications.

## Old vs new dependency loop

| Step | Old toolkit | New toolkit |
|---|---|---|
| Edit `pyproject.toml` | Same | Same |
| Rebuild project image | **2-5 min** (pip resolve + GDAL compile + npm) | not needed |
| Nuke the `venv` volume | required | not needed |
| Recreate containers | 30-60s (downloading init bundles) | not needed |
| `uv sync` into running container | n/a — venv was baked in | **1-3 s** |
| Total wall time for "add `humanize`" | ~3 min | ~3 s |

The same image cache also survives day-to-day — no `docker system prune`
rituals to recover disk from stale rebuilds.

## Debugging with debugpy

The dev overlay exposes `5678:5678` and starts `web` under
`python -m debugpy --listen 0.0.0.0:5678`.

- **VSCode**: use the "Python: Remote Attach" launch config pointing at
  `localhost:5678`, with path mappings `${workspaceFolder}` → `/app`.
- **PyCharm**: Run → Edit Configurations → "Python Debug Server",
  host `localhost`, port `5678`.
- **CLI**: `python -m debugpy --connect localhost:5678 --wait-for-client …`.

The runserver process doesn't block on attach — hit the endpoint you want
to trace, then attach the debugger to catch the next request.

## File watch and hot reload

`compose.dev.yaml` registers `develop.watch` rules:

| Path | Action |
|---|---|
| `**/*.py`, `**/*.html`, `**/*.css`, `**/*.js`, `**/*.vue` | `sync` — copied in-place; Django autoreload / webpack HMR picks them up |
| `pyproject.toml`, `uv.lock` | `rebuild` — these change the image's base layers |

`sync` updates happen in well under a second. If you've changed
dependencies, running `docker compose exec web uv sync` is faster and
less disruptive than letting `rebuild` fire.

## Project-specific services

Drop a `compose.extras.yaml` at your repo root. `arches-toolkit dev`
auto-includes it. See [compose-extras.md](compose-extras.md) for the
convention and worked examples.

## Troubleshooting

### `permission denied` on a volume-mounted path

All services run as UID 1000. If a bind-mount or named volume ends up
owned by a different UID (common on first run when a previous iteration
left root-owned files behind), reset ownership:

```sh
docker compose down -v    # WARNING: destroys all named-volume data
docker compose up --watch
```

For a single volume:

```sh
docker compose run --rm --user root web chown -R 1000:1000 /var/arches/uploadedfiles
```

### Stage 6 caveat — `frontend_configuration` writes

Until the Stage 6 patch lands upstream, Arches writes frontend
configuration to the installed package's hardcoded path, *not* the
`ARCHES_FRONTEND_CONFIGURATION_DIR` env var. As a result, the `init`
service currently needs to run as root (or in a writable overlay) on some
hosts. **Non-root runtime depends on Stage 6.** The compose files
pre-wire the env var so the switch is invisible once the patch ships.

### Port already in use

Edit the left-hand side of the `ports:` mapping in `compose.dev.yaml` (or
add a `compose.extras.yaml` that overrides just the port) — for example,
`8088:8000` if something else is on 8000.

### Elasticsearch refuses to start / OOMKilled

ES 8 defaults assume 1 GiB heap. On a laptop with tight memory, drop it:

```sh
ES_JAVA_OPTS='-Xms512m -Xmx512m' arches-toolkit dev
```

On Linux hosts, also ensure:

```sh
sudo sysctl -w vm.max_map_count=262144
```

### Reset the stack completely

```sh
docker compose down -v     # drops named volumes — irreversible
docker compose build --no-cache
arches-toolkit dev
```

### `uv sync` in the container is slow

The first `uv sync` on a cold `venv` volume resolves the full dep tree
and can take 30-60s. Subsequent syncs re-use the lockfile and the cache
mount and complete in a few seconds. If you're still seeing minutes,
`docker volume inspect <project>_venv` — a corrupt or full volume is
usually the cause; `docker volume rm <project>_venv` and let it
repopulate.

## See also

- [compose-extras.md](compose-extras.md) — project-specific services
- [../PLAN.md](../PLAN.md) — architectural context
- [../TASKS.md](../TASKS.md) — delivery roadmap
- [../docker/project/compose.yaml](../docker/project/compose.yaml)
- [../docker/project/compose.dev.yaml](../docker/project/compose.dev.yaml)
