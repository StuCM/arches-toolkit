# arches-toolkit

Replacement for the Flax & Teal Arches container toolkit. Projects consume a single installed CLI plus a base image — no `Dockerfile`, `docker-compose.yml`, `Makefile`, or `install_app.py` in the project tree.

**Status**: Phase 1 working end-to-end on a local smoke test. Pilot migration (Catalina) pending. See [PLAN.md](PLAN.md) and [TASKS.md](TASKS.md).

## Install

```bash
git clone https://github.com/flaxandteal/arches-toolkit.git
cd arches-toolkit

# 1. Build the base image locally (only needed until GHCR publish lands)
./docker/base/build.sh --arches-ref stable/8.1.0 --tag arches-toolkit-local-test

# 2. Install the CLI as a persistent tool
uv tool install -e ./cli
arches-toolkit --version
```

## Everyday flow

### Create a project

```bash
arches-toolkit init mything          # scaffolds via arches-admin + writes .env, .dockerignore, settings.py overrides
cd mything
arches-toolkit dev --build           # first run: builds project image, starts stack
                                     # (watch: http://localhost:8000)
arches-toolkit setup-db              # ONE-TIME: setup_db, ES indexes, system-settings resource
                                     # → /settings/ now works, /search/ now works
                                     # add --dev-users to seed admin/admin; --yes to skip confirm
```

After that, stop with `arches-toolkit down`, start again with `arches-toolkit dev` (no `--build`, no setup-db — their work is persisted in volumes).

### Daily development

```bash
arches-toolkit dev                   # bring the stack up (watches files)
arches-toolkit logs -f web           # tail a service
arches-toolkit ps                    # what's running
arches-toolkit exec web bash         # shell into a container
arches-toolkit restart web           # restart one service (~2s; no rebuild)
arches-toolkit down                  # stop everything (preserves volumes)
arches-toolkit down -v               # stop and wipe volumes (destructive)
```

### Editing Python or frontend code

- **`.py` files**: Django runserver autoreloads (~2s).
- **`.vue` / `.ts` / `.scss`**: webpack devserver HMR (~200ms).
- **Python deps**: edit `pyproject.toml` then `arches-toolkit exec web uv sync` (~2s).
- **npm deps**: edit `package.json` then `arches-toolkit exec webpack npm install` (~10s).
- **Migrations**: `arches-toolkit exec web python manage.py makemigrations && migrate`.

No image rebuilds in any of the above.

### Editing Arches core live (optional)

Pass a path to a local Arches clone via `ARCHES_SRC`; the CLI detects it and bind-mounts over `/opt/arches` across every container:

```bash
export ARCHES_SRC=~/git/archesproject/arches
arches-toolkit dev
```

Because Arches is installed *editable* in the base image, your prints / breakpoints / small patches apply instantly without a rebuild.

## Apps (Arches plugins)

Declare apps in `apps.yaml` at the project root:

```yaml
apps:
  - package: arches-her
    source: pypi
    version: "~=2.0"
    mode: release
  - package: arches-orm
    source: git
    repo: https://github.com/flaxandteal/arches-orm.git
    ref: main
    mode: develop          # bind-mounts ../arches-orm into web + worker
```

```bash
arches-toolkit add-app arches-her --source pypi --version "~=2.0"
arches-toolkit sync-apps             # writes pyproject.toml deps + compose.apps.yaml
```

## Scaffolding artifacts

`arches-toolkit create` stamps out the files you'd otherwise copy from another
project. Templates are version-scoped (Arches 7.6 and 8.1 ship today) and
register commands are echoed for you to run — never executed automatically.

```bash
arches-toolkit create widget my_widget --datatype string
arches-toolkit create card-component my_card
arches-toolkit create plugin my_plugin --slug my-plugin --icon "fa fa-star"
arches-toolkit create report my_report
arches-toolkit create function my_fn --type node
arches-toolkit create datatype my_type
arches-toolkit create search-filter my_filter --type filter
arches-toolkit create component my_component
arches-toolkit create app demo --path ../
```

By default files land in the current project. Use `--app <dir>` to target an
existing `arches-<name>` application package instead. Pass `--knockout` on
widget / card-component / plugin / function to also emit the legacy KO shim
alongside the Vue3 primary. See [docs/create.md](docs/create.md) for the full
reference.

## What lives where

| Location | Contents |
|---|---|
| **Your project** | `pyproject.toml`, `apps.yaml`, `.env`, source code, `settings.py`, `webpack/`, `package.json` — *that's it*. No `Dockerfile`, no compose files. |
| **arches-toolkit repo** (`cli/src/arches_toolkit/_data/`) | Project `Dockerfile`, `compose.yaml`, `compose.dev.yaml`, `init.sql`, `compose.arches-src.yaml` — shipped as Python package data |
| **arches-toolkit repo** (`docker/base/`) | `Dockerfile` that builds the base image from upstream Arches + patches |
| **arches-toolkit repo** (`docker/base/patches/`) | `*.patch` files applied via `git am` during base image build. Current: one patch parameterising the `frontend_configuration` path. |

## Patches against Arches core

```bash
arches-toolkit patch start my-fix          # clones arches into ~/.cache/arches-toolkit/patches/my-fix
cd ~/.cache/arches-toolkit/patches/my-fix  # edit files, commit, etc.
# ... git commit -am "..." with Upstream/Last-reviewed/Reason in the message ...
cd -
arches-toolkit patch finish my-fix --reason "..." --upstream "none yet"

arches-toolkit patch list                  # table of patches + last-reviewed
arches-toolkit patch status                # same, plus GitHub PR state if GH_TOKEN set
arches-toolkit patch renew my-fix          # bump Last-reviewed to today
```

## Changing the Arches base

The toolkit's base image pins an upstream Arches ref at build time. The default is `stable/8.1.0`, consumed via the floating tag `latest-arches-stable-8.1.0` on `ghcr.io/flaxandteal/arches-toolkit`.

**To follow a different published ref** — set in your project's `.env`:

```bash
ARCHES_TOOLKIT_TAG=latest-arches-dev-8.1.x          # floating: follows dev/8.1.x
ARCHES_TOOLKIT_TAG=<toolkit-sha>-arches-stable-8.1.0  # pinned: reproducible
```

Then `arches-toolkit down && arches-toolkit dev --build` to rebuild your project image against the new base. If you're also using `ARCHES_SRC`, check out the matching ref in your clone too (see [docs/local-arches-src.md#version-alignment](docs/local-arches-src.md#version-alignment)).

**To build against a ref the CI hasn't published** — e.g. a specific commit SHA, a feature branch, or a fork — build the base image locally. `ARCHES_REF` accepts branches, tags, and commit SHAs:

```bash
./docker/base/build.sh --arches-ref v8.1.0       # tag
./docker/base/build.sh --arches-ref abc1234      # commit SHA
./docker/base/build.sh --arches-ref my-branch --arches-repo https://github.com/your-fork/arches.git
```

See [docker/base/README.md](docker/base/README.md) for the full tag scheme and CI publishing matrix.

## Env vars at a glance

### Per-environment (live in `.env` or cluster secrets)

| Var | Purpose |
|---|---|
| `PGUSER`, `PGPASSWORD`, `PGDBNAME` | Postgres connection |
| `DEBUG` | Django debug mode |

### Per-project (live in `.env`; written by `arches-toolkit init`)

| Var | Purpose |
|---|---|
| `PROJECT_NAME`, `PROJECT_PACKAGE` | Python package name |
| `PROJECT_IMAGE`, `PROJECT_TAG` | Built image name:tag |
| `ARCHES_TOOLKIT_IMAGE`, `ARCHES_TOOLKIT_TAG` | Base image to `FROM` |
| `DJANGO_SETTINGS_MODULE`, `WSGI_APP`, `CELERY_APP` | Django wiring |

### Toolkit internals (set automatically by the CLI)

| Var | Purpose |
|---|---|
| `ARCHES_TOOLKIT_DOCKERFILE` | Absolute path to the project Dockerfile inside the installed CLI |
| `ARCHES_TOOLKIT_INIT_SQL` | Absolute path to `init.sql` inside the installed CLI |
| `ARCHES_SRC` (optional) | Host path to a local Arches clone to bind-mount over `/opt/arches` |

If you find yourself running raw `docker compose` commands from a project, you'll need to export the toolkit internals first. Better: use the CLI wrappers (`arches-toolkit logs|ps|exec|restart|down|build`) — they set these for you.

## Command reference

| Command | Description |
|---|---|
| `arches-toolkit init <name>` | Scaffold a new Arches project (one-time per project) |
| `arches-toolkit create <kind> <name>` | Scaffold a widget / plugin / component / app / etc. (see [docs/create.md](docs/create.md)) |
| `arches-toolkit dev` | `docker compose up --watch` against the toolkit baseline + project overlays |
| `arches-toolkit setup-db [--dev-users] [--yes]` | **Destructive, one-time**: `setup_db --force` to seed DB + ES + system settings. `--dev-users` seeds test accounts (admin/admin); `--yes` skips the confirm |
| `arches-toolkit add-app` | Add an Arches app to `apps.yaml` |
| `arches-toolkit sync-apps` | Project `pyproject.toml` + `compose.apps.yaml` from `apps.yaml` |
| `arches-toolkit logs [-f] [service]` | `docker compose logs` wrapper |
| `arches-toolkit ps` | `docker compose ps` wrapper |
| `arches-toolkit exec <service> <cmd…>` | `docker compose exec` wrapper |
| `arches-toolkit restart [service…]` | `docker compose restart` wrapper |
| `arches-toolkit down [-v]` | `docker compose down` wrapper (`-v` wipes volumes) |
| `arches-toolkit build` | `docker compose build` (no start) |
| `arches-toolkit manage <cmd…>` | Run `python manage.py <cmd…>` inside the web container |
| `arches-toolkit patch start/finish/list/renew/status` | Maintain the Arches patch series |

## What's left before this replaces the old toolkit

| Item | Status |
|---|---|
| Pilot migration of a real project (Catalina) | Pending |
| Publish base image to `ghcr.io/flaxandteal/arches-toolkit` | Pending |
| Publish CLI to PyPI (`uvx arches-toolkit …` from any machine) | Pending |
| Webpack HMR port (internal 8080 vs mapped 9000) | Pending |
| `HOST_UID` build arg for non-1000 host users | Pending |
| Prod target: `COPY webpack-stats.json` from frontend stage | Pending |
| Helm chart updates (Phase 2) | Deferred |
| Project-CI reusable workflow (Phase 2) | Deferred |
| Upstream PRs for patches + the one bucket-A commit | Deferred |

## How this works under the hood

The CLI is a thin wrapper around `docker compose`. Every subcommand:

1. Locates baseline `compose.yaml` / `compose.dev.yaml` / `Dockerfile` / `init.sql` via `importlib.resources` (they ship as package data inside the installed CLI).
2. Auto-discovers `compose.apps.yaml` and `compose.extras.yaml` in the project root and layers them on top.
3. Sets the `ARCHES_TOOLKIT_DOCKERFILE` and `ARCHES_TOOLKIT_INIT_SQL` env vars so compose can interpolate the absolute paths the YAML references.
4. Passes `--project-directory <cwd>` so relative references inside the compose files (e.g. `context: .`) resolve to the project, not the site-packages path.
5. Exec/inherit stdio so output streams live.

See [cli/src/arches_toolkit/commands/](cli/src/arches_toolkit/commands/) for the five files this is implemented in.

## Links

- [PLAN.md](PLAN.md) — design rationale
- [TASKS.md](TASKS.md) — Phase 1 work list
- [docs/incremental-migration.md](docs/incremental-migration.md) — adopt the toolkit for dev while keeping legacy CI — the recommended path for projects already deploying to production
- [docs/migrating-quartz.md](docs/migrating-quartz.md) — worked migration example
- [docs/create.md](docs/create.md) — scaffolding apps, widgets, plugins, etc. and the full `create app` lifecycle
- [docs/local-arches-src.md](docs/local-arches-src.md) — bind-mount a local Arches clone via `ARCHES_SRC` to debug Arches core live
- [docs/fork-inventory.md](docs/fork-inventory.md) — why the old F&T fork of Arches is being retired
- [docs/local-dev.md](docs/local-dev.md) — dev loop notes (mostly superseded by this README)
- [docs/compose-extras.md](docs/compose-extras.md) — adding project-specific services
