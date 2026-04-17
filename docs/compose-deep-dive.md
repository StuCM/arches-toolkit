---
created: 2026-04-16
audience: engineers debugging the toolkit's runtime stack
scope: compose topology, env vars, volumes, Arches integration points
---

# Compose deep-dive

Reference for the toolkit's docker compose configuration: every service, every env var, every volume, and why. Written for the case where something breaks at 17:00 on a Friday and the person debugging it has not touched these files in three months.

The toolkit ships two compose files as package data, loaded by `arches-toolkit dev`:

- [compose.yaml](../cli/src/arches_toolkit/_data/compose.yaml) — prod-shaped baseline. All eight services, all named volumes. Runnable on its own against the prod image target.
- [compose.dev.yaml](../cli/src/arches_toolkit/_data/compose.dev.yaml) — dev overlay. Switches to `target: dev`, bind-mounts the project source at `/app`, exposes ports, adds debugpy, redirects frontend configuration to the source tree, registers watch rules.

Two further overlays appear on demand:

- `compose.arches-src.yaml` (package data, included when `ARCHES_SRC` is set) — bind-mounts a local Arches checkout over the image's editable install.
- `compose.apps.yaml` and `compose.extras.yaml` (project-owned, in project root) — auto-included by the CLI when present. See [compose-extras.md](compose-extras.md).

The CLI assembles the `-f` chain in `dev.py:_compose_argv()` — order matters for merge semantics (see [YAML anchors and file merging](#yaml-anchors-and-file-merging)).

## Architecture: one writer, many readers

Arches is a Django application that runs in three process flavours — WSGI (web), API WSGI (api), and Celery (worker). All three boot the same Django app registry, which means all three trigger `ArchesAppConfig.ready()` on startup. `ready()` has side effects that write to disk — most notably `generate_frontend_configuration()` which emits JSON manifests consumed by webpack and TypeScript.

For modern deployment (non-root containers, readOnlyRootFilesystem in k8s) this is a problem: you cannot have three pods racing to write the same files on a code tree that is supposed to be read-only. The toolkit solves this with an **init + peer** pattern:

```
                  ┌──────────────────────────────┐
                  │ Named volume                 │
                  │ frontend_configuration       │
                  │   urls.json                  │
                  │   webpack-metadata.json      │
                  │   tsconfig-paths.json        │
                  │   rspack-metadata.json       │
                  └──────────────────────────────┘
                          ▲              ▲
                     rw   │              │  ro
                          │              │
                  ┌───────┴──────┐   ┌───┴───────────┐
                  │ init (once)  │   │ web / worker  │
                  │              │   │ api / webpack │
                  │ migrates DB, │   │ (long-lived)  │
                  │ writes files │   └───────────────┘
                  └──────────────┘
```

- **init** mounts the shared volume `rw`, runs `manage.py migrate`, and exits. `migrate` boots Django, which triggers `ready()`, which writes the four JSON files.
- **Peer services** mount the same volume `ro`. Their `ready()` also tries to write; the kernel returns `EROFS`; the [Stage 6 patch](#stage-6-patch-frontend_configuration) catches it and carries on.

Compose sequences this with `depends_on: init: condition: service_completed_successfully`, so peers don't start until init has exited zero.

## Services

### Infrastructure layer (neutral — no Arches code)

| Service | Image | Purpose | Ports (dev) |
|---|---|---|---|
| `db` | `postgis/postgis:14-3.4` | PostgreSQL + PostGIS — Arches' primary store | 5432 (via `compose.extras.yaml` if exposed) |
| `elasticsearch` | `elasticsearch:8.4.0` | Search index — Arches indexes resources for fast lookup | 9200 (if exposed) |
| `rabbitmq` | `rabbitmq:3-management` | Broker for Celery tasks (imports, exports, bulk ops) | 5672 / 15672 |
| `cantaloupe` | `uclalibrary/cantaloupe:5.0.3-0` | IIIF image server — handles tile serving for uploaded images | 8182 |

All four are healthchecked; init and Arches services `depends_on: service_healthy` before starting.

**`init.sql`** mounts into `db` at `/docker-entrypoint-initdb.d/init.sql` via the `ARCHES_TOOLKIT_INIT_SQL` env var (set by the CLI from package data). Runs once on first container start — creates extensions and role grants Arches needs.

### Arches layer (all share the `*arches` or `*arches-dev` anchor)

| Service | Role | Writes to fs? | Command |
|---|---|---|---|
| `init` | One-shot setup | Yes (rw mounts) | `migrate` → `createcachetable` (→ `collectstatic` in prod). Dev wraps this in a warm-start probe — see [Warm-start probe](#warm-start-probe). |
| `web` | HTTP (user-facing) | No (ro peers) | `gunicorn` (prod) / `runserver + debugpy` (dev) |
| `api` | HTTP (API — separate port/worker pool) | No | `gunicorn` (prod) / `runserver` (dev) |
| `worker` | Celery worker | No | `celery worker` |
| `webpack` | Dev-only frontend bundler | No (reads ro mount of frontend_configuration) | `npm run start` (webpack-dev-server on :9000) |

`webpack` only exists in the dev overlay. Prod builds the bundle at image build time (the `frontend` stage in the Dockerfile) and serves the result via nginx.

## YAML anchors and file merging

### Intra-file anchors (`&` / `*` / `<<:`)

Each compose file defines an anchor for the shared Arches service config:

```yaml
x-arches: &arches        # compose.yaml
  image: ...
  environment: { ... }
  volumes: [ ... ]
  depends_on: { ... }

services:
  web:
    <<: *arches          # merge the anchor's keys into this service
    command: [ "gunicorn", ... ]
```

`x-` prefixes are compose-ignored — the convention for "reusable YAML fragment, not a service."

**Key replacement, not deep merge.** If a service re-declares a key that the anchor also has, the whole key is replaced. This is why the `init` override in compose.yaml re-lists all six volume mounts — just to drop `:ro` on one of them.

### Inter-file merging (`-f a.yaml -f b.yaml`)

Compose merges files in the order given. List fields like `volumes:` and `ports:` **concatenate, deduplicated by target path** (the `:target` part of a mount, the container-side port of a mapping). Scalar fields like `command:` replace.

So the effective volumes for `web` in dev = (base `*arches` volumes from compose.yaml) ∪ (`*arches-dev` volumes from compose.dev.yaml), with dev wins on conflicts. Dev adds `.:/app` and replaces the `:ro` flag on frontend_configuration.

Run `docker compose config` to see the fully merged view. Invaluable when debugging unexpected behaviour.

## Environment variables

### Set per project (required)

| Var | Where it comes from | Consumed by |
|---|---|---|
| `PROJECT_NAME` | project `.env` | compose build args; becomes image tag component |
| `PROJECT_PACKAGE` | project `.env` (defaults to `PROJECT_NAME`) | compose build args; Python package name for imports |
| `DJANGO_SETTINGS_MODULE` | project `.env` | Django — which settings module to load |
| `WSGI_APP` | project `.env` | gunicorn — `<pkg>.wsgi:application` |
| `CELERY_APP` | project `.env` | celery worker `-A` flag |

The `:?set in project .env` syntax in the compose files makes missing values a hard fail at `docker compose up` time, not a confusing runtime error.

### Set by compose (Arches-facing)

| Var | Value | Purpose |
|---|---|---|
| `ARCHES_FRONTEND_CONFIGURATION_DIR` | `/var/arches/frontend_configuration` (prod) / `/app/frontend_configuration` (dev) | See [Stage 6 patch](#stage-6-patch-frontend_configuration) |
| `ARCHES_UPLOADED_FILES_DIR` | `/var/arches/uploadedfiles` | User uploads. Named volume, survives container restarts. |
| `PGHOST` / `PGPORT` / `PGUSER` / `PGPASSWORD` / `PGDBNAME` | wired to the `db` service | Django DB connection |
| `ESHOST` / `ESPORT` | `elasticsearch:9200` | Arches search config |
| `RABBITMQ_URL` | `amqp://<user>:<pass>@rabbitmq:5672//` | Celery broker |
| `CANTALOUPE_HTTP_ENDPOINT` | `http://cantaloupe:8182/` (default) | URL embedded in IIIF manifests. **Browser-facing** — the default container-DNS value works for server-side calls but a browser hitting `/search` won't resolve it. Override via project `.env` to `http://localhost:8182/` for local dev, or the real public hostname in prod. |

### Set by compose (Python/Django-facing, dev only)

| Var | Value | Purpose |
|---|---|---|
| `DEBUG` | `True` | Django debug mode — tracebacks, static file serving via `runserver` |
| `PYTHONUNBUFFERED` | `1` | Flush stdout/stderr immediately — otherwise docker logs appear in bursts |
| `PYTHONDONTWRITEBYTECODE` | `1` | Don't litter the bind-mounted source tree with `__pycache__/` owned by the container user |

### Set by the CLI (`arches-toolkit dev`)

| Var | Points to | Why via env |
|---|---|---|
| `ARCHES_TOOLKIT_DOCKERFILE` | package data `Dockerfile` | The Dockerfile lives inside the CLI wheel; compose needs an absolute path |
| `ARCHES_TOOLKIT_INIT_SQL` | package data `init.sql` | Same reason — mounted into the `db` service |
| `ARCHES_TOOLKIT_IMAGE` / `ARCHES_TOOLKIT_TAG` | base image coordinates | Override to pin a specific base image; defaults to `ghcr.io/flaxandteal/arches-toolkit:latest-arches-stable-8.1.0` |

## Volumes

Named volumes declared in [compose.yaml:143-150](../cli/src/arches_toolkit/_data/compose.yaml#L143-L150). All are rw for init, ro (or bind-mounted rw) for peers.

| Volume | Container path | Writer | Reader(s) | Contents |
|---|---|---|---|---|
| `postgres_data` | `/var/lib/postgresql/data` | `db` only | — | PostgreSQL cluster files |
| `es_data` | `/usr/share/elasticsearch/data` | `elasticsearch` only | — | Elasticsearch indices |
| `frontend_configuration` | `/var/arches/frontend_configuration` | `init` | `web`, `worker`, `api`, `webpack` | JSON manifests (urls, webpack-metadata, tsconfig-paths, rspack-metadata) |
| `uploadedfiles` | `/var/arches/uploadedfiles` (Arches services) / `/imageroot` (cantaloupe) | `web`, `worker`, `api` (user uploads via Arches views) | same + `cantaloupe` (reads images for tile serving) | User-uploaded resource files. Cantaloupe mounts it at `/imageroot` to match the `uclalibrary/cantaloupe` image's default `BasicLookupStrategy` path prefix, which is why no `CANTALOUPE_FILESYSTEMSOURCE_*` env vars are set. |
| `static_root` | `/var/arches/static_root` | `init` (via `collectstatic` in prod) | nginx in prod; **unused in dev** | Collected static files for prod CDN/nginx serving |
| `logs` | `/var/arches/logs` | all Arches services | — | Django logger output (if configured for file logging) |
| `venv` | `/venv` | image build + `uv sync` at runtime | all Arches services | The Python virtualenv — shared across services so `uv sync` in one updates all |

### Why the `venv` volume is shared

Arches dev iterations frequently add Python packages. Rebuilding the image every time a dep changes is slow. Putting the venv on a named volume means `docker compose exec web uv sync` updates the venv on the shared volume; next request, `web` sees the new package. `worker` and `api` see it too because they mount the same volume. This is the core value prop of the toolkit's dev loop — see [local-dev.md](local-dev.md) §"Old vs new dependency loop."

### Why `frontend_configuration` uses a named volume and not a bind mount

In **prod**, the files are ephemeral — regenerated from code state on every init run. Nothing on the host needs to see them. A named volume is simpler and doesn't leak files into the deployment artefact.

In **dev**, we *do* want them on the host so the editor's TypeScript language server can read `tsconfig-paths.json`. The dev overlay handles this by setting `ARCHES_FRONTEND_CONFIGURATION_DIR=/app/frontend_configuration` — redirecting writes into the `.:/app` bind mount. The named volume at `/var/arches/frontend_configuration` is still declared (inherited from `*arches`) but nothing reads or writes it in dev.

## Stage 6 patch: frontend_configuration

See [docker/base/patches/0001-frontend_configuration-honour-ARCHES_FRONTEND_CONFIG.patch](../docker/base/patches/0001-frontend_configuration-honour-ARCHES_FRONTEND_CONFIG.patch). This is the single most important change the toolkit makes to Arches for non-root/read-only deployment. Without it, the compose/k8s topology doesn't work.

### What upstream Arches does

`arches/app/apps.py:ArchesAppConfig.ready()` calls `generate_frontend_configuration()` on every Django app-registry load. That function writes four files to `<base_path>/../frontend_configuration/`, where `base_path` is computed from the installed Arches package location.

Two problems:

1. **Path is inside the code tree.** Writing there means the code tree must be writable. Incompatible with `readOnlyRootFilesystem: true` in k8s and with running as non-root on images that don't `chown` the site-packages dir.
2. **Every process writes.** web, worker, api all trigger it — in a shared-volume setup where only one pod should be canonical, this is a race.

### What the patch changes

**a. Env var for relocation.** `ARCHES_FRONTEND_CONFIGURATION_DIR`, when set, replaces the default path verbatim. The four writers (`_generate_frontend_configuration_directory`, `_generate_urls_json_file`, `_generate_webpack_configuration_file`, `_generate_tsconfig_paths_file`) all read from one helper `_frontend_configuration_dir(base_path)` that checks the env var first, falls back to the legacy path.

**b. Tolerate read-only filesystems.** The outer `try:` in `generate_frontend_configuration()` catches `OSError` and checks `errno`. On `EROFS` (read-only fs) or `EACCES` (permission denied), it logs and returns zero. Any other OSError re-raises.

**c. Webpack reads the env var too.** `webpack/webpack.common.js` (both in Arches' source and in the template used for new projects) honours `ARCHES_FRONTEND_CONFIGURATION_DIR` when resolving `webpack-metadata.json`.

### Deployment matrix

| Scenario | `ARCHES_FRONTEND_CONFIGURATION_DIR` | Mount mode | Expected behaviour |
|---|---|---|---|
| Compose prod, `init` | `/var/arches/frontend_configuration` | `rw` on named volume | Writes succeed. |
| Compose prod, `web`/`worker`/`api` | `/var/arches/frontend_configuration` | `ro` on named volume | Writes fail with `EROFS`; caught; pod boots. |
| Compose dev, `init` | `/app/frontend_configuration` | `rw` on `.:/app` bind mount | Writes succeed, files appear on host. |
| Compose dev, peers | `/app/frontend_configuration` | `rw` on bind mount | Writes succeed (harmlessly re-write). Named volume at `/var/arches/frontend_configuration` is dead. |
| Compose dev, `webpack` | `/app/frontend_configuration` | `rw` on bind mount | Reads via webpack.common.js honouring env var. |
| k8s | `/var/arches/frontend_configuration` | emptyDir: init rw, peers ro | Same as compose prod. `readOnlyRootFilesystem: true` works because writes go to emptyDir, not root fs. |

### Files written

| File | Purpose |
|---|---|
| `urls.json` | Reverse-mapping of Django URL names → paths. Consumed by frontend JS to build links without hardcoding routes. |
| `webpack-metadata.json` | App paths, entry points, plugin list. Read by `webpack.common.js` on each webpack invocation. |
| `tsconfig-paths.json` | TypeScript path aliases — lets `@arches/*` imports resolve to installed app locations. Read by tsc and the editor's language server. |
| `rspack-metadata.json` | Parallel to webpack-metadata for projects using rspack. |

The data is derived from `INSTALLED_APPS`, URL patterns, and each Arches app's `arches.json` manifest. It only changes when code changes — no runtime regeneration is ever needed outside of deploy.

## Dev overlay specifics

### Warm-start probe

Dev `init` wraps its body in a pre-Django SQL probe so warm restarts don't pay the full Django-boot cost. Implemented in [compose.dev.yaml](../cli/src/arches_toolkit/_data/compose.dev.yaml) on the `init` service as an inline shell + `psycopg2` one-liner.

The probe connects with the same `PG*` env vars the Django app would use and runs `SELECT 1 FROM django_migrations LIMIT 1`. If a row comes back, init echoes a skip message and exits zero; otherwise it falls through to `migrate --noinput` + `createcachetable` as before.

| Scenario | Probe result | What init does |
|---|---|---|
| First-ever `dev up` (fresh `postgres_data` volume) | Connection succeeds but `django_migrations` doesn't exist → exception → exit 1 | Full migrate + createcachetable |
| Warm restart after a clean stop | Rows present → exit 0 | Skip (sub-second) |
| After `arches-toolkit setup-db` | `setup_db --force` drops the DB, so `django_migrations` is empty → exit 1 | Full migrate + createcachetable |
| DB up but wrong credentials | psycopg2 raises on connect → exit 1 | Full migrate (which will also fail — same failure mode as before) |

**Known tradeoff:** if you add a new Django migration file in code, the probe still says "initialized" and skips it. To apply: `arches-toolkit manage migrate` explicitly, or wipe via `setup-db` if it's safe to lose data. Not dangerous — just silent. The original arches-quartz entrypoint had the same property.

**Prod keeps the always-run init** (see [compose.yaml:128-134](../cli/src/arches_toolkit/_data/compose.yaml#L128-L134)). In prod the expensive step is `collectstatic`, which wants a different gate (source-mtime stamp), and prod restarts are rare enough that the extra few seconds don't justify the added path.

### Postgres tuning

The dev overlay overrides `db.command:` with four postgres knobs that trade durability for speed:

```
-c shared_buffers=256MB
-c fsync=off
-c synchronous_commit=off
-c full_page_writes=off
```

`fsync=off` in particular means a kernel crash **will** corrupt the DB. This is acceptable in dev — worst case is `arches-toolkit setup-db` — but would be catastrophic in prod. That's why the knobs live in `compose.dev.yaml` and not the base file.

Borrowed from the arches-quartz `db.command:` block. Swaps in on `dev up`; won't take effect with `restart` alone because compose only re-reads commands when the container is recreated.

### Bind mount `.:/app`

The single most important dev feature. Replaces the image's baked-in `/app` (the project source copy from `COPY . /app`) with a live view of the host repo. Edits in your editor are visible inside the container immediately, no rebuild.

Watch rules in `develop.watch` (lines 30-44) mirror the bind mount for Windows/Mac hosts where bind-mount performance is poor — compose's watch feature copies files via a side channel instead. On Linux the bind mount alone is enough, but the watch rules are harmless.

`pyproject.toml` and `uv.lock` are registered as `rebuild` triggers — changing them invalidates the venv, so compose rebuilds the image rather than syncing.

### debugpy on :5678

`web` runs under `python -m debugpy --listen 0.0.0.0:5678 manage.py runserver ...`. `runserver` doesn't block on debugpy attach — requests flow normally. Attach from VSCode/PyCharm (see [local-dev.md](local-dev.md) §Debugging) to set breakpoints on demand.

### webpack service

`npm run start` runs `webpack serve --config webpack/webpack.config.dev.js` on port 9000 with HMR. The bootstrap at the top of its command checks a stamp file (`node_modules/.arches-toolkit-install-stamp`) — if missing, it wipes `node_modules` and re-runs `npm install`. This handles the case where the host's `node_modules` was populated by a different Node version or a different platform.

**Failure mode:** webpack reads `webpack-metadata.json` via the env var `ARCHES_FRONTEND_CONFIGURATION_DIR`. If init hasn't run (or hasn't finished), that file doesn't exist. Symptom: `ENOENT: no such file or directory, open '/app/frontend_configuration/webpack-metadata.json'`. Fix: `arches-toolkit dev logs init` to see what init did; if init crashed, fix that first.

### `ARCHES_SRC` overlay

If you set `ARCHES_SRC=/path/to/your/arches/checkout` before `arches-toolkit dev`, the CLI adds `compose.arches-src.yaml` to the `-f` chain. That overlay bind-mounts your Arches source over `/opt/arches` in the container. Lets you edit Arches itself (add logging, test a patch) without rebuilding the base image.

Depends on the base image having installed Arches with `uv pip install -e` — otherwise the overlay replaces the installed package with an un-built source tree.

## Debugging runbook

### Webpack ENOENT on webpack-metadata.json

1. `docker compose logs init | tail` — did init exit with status 0?
2. If init failed: the real error is somewhere in the migrate/ready() output. Likely DB connectivity, missing settings, or a broken patch.
3. If init succeeded but file is missing: check `ARCHES_FRONTEND_CONFIGURATION_DIR` on both init and webpack services match. A mismatch is the classic bug.
4. `docker compose exec web ls /app/frontend_configuration/` (dev) or `docker compose exec web ls /var/arches/frontend_configuration/` (prod) — confirm the four files exist.

### Peer pod crashes with `PermissionError` on frontend_configuration

The Stage 6 patch isn't applied to the image. Check that the base image tag in use (`ARCHES_TOOLKIT_TAG`) was built with the patches in `docker/base/patches/` applied. See [fork-inventory.md](fork-inventory.md) for patch provenance.

### Init hangs on `collectstatic`

Dev overlay skips `collectstatic` — the `init` service's command in [compose.dev.yaml](../cli/src/arches_toolkit/_data/compose.dev.yaml) only runs `migrate` + `createcachetable` (via the warm-start probe). If you're seeing this in dev, your compose file is out of date. In prod, `collectstatic` walking ~93k files takes 30-60s — normal.

### `uv sync` into running container has no effect

The venv volume is shared across Arches services, but each service must reload Python to see the new package. `runserver` autoreloads on `.py` file changes but *not* on package install. Restart the affected service: `docker compose restart web`.

### UID/permission issues on bind-mounted paths

All Arches services run as UID 1000 (`user: "1000:1000"` in compose.yaml:16). If your host user is UID 1000 too (typical single-user Linux), bind-mounted writes work without fuss. If not, expect EACCES on directories the container tries to write. Either:
- Change your host user to UID 1000 (not recommended), or
- Add `user: "${UID}:${GID}"` to a `compose.extras.yaml` and export those in your shell.

## Kubernetes mapping

The compose file is the contract. The k8s chart (in `chart/`) mirrors the same topology:

| compose | k8s |
|---|---|
| Service inheriting `*arches` | Deployment using the shared podspec fragment |
| `init` service | initContainer in each peer Deployment, or a Job |
| `frontend_configuration` named volume | emptyDir shared between initContainer and app container, or a PVC |
| `:ro` mount | `volumeMounts[].readOnly: true` |
| `depends_on: service_healthy` | `initContainers` + readiness probes |
| `user: "1000:1000"` | `securityContext.runAsUser: 1000`, `runAsGroup: 1000` |
| (implicit) | `securityContext.readOnlyRootFilesystem: true` — enabled by Stage 6 patch |
| env vars from compose | ConfigMap or explicit `env:` entries |

Chart is currently empty; when it lands, the mapping above is the starting contract.

## Related docs

- [local-dev.md](local-dev.md) — user-facing quick start and common workflows
- [compose-extras.md](compose-extras.md) — project-specific service additions
- [fork-inventory.md](fork-inventory.md) — which Arches patches we carry and why
- [../PLAN.md](../PLAN.md) — architectural context
- [../docker/base/patches/](../docker/base/patches/) — maintained patches against the Arches fork
