# Migrating arches-quartz to arches-toolkit

Worked example of converting an existing F&T Arches project to the toolkit-managed dev loop. Derived from the pilot conversion of `arches-quartz` carried out on branch `pilot/arches-quartz`.

## Before: what quartz ships today

```
arches-quartz/
  quartz/
    docker/
      Dockerfile, Dockerfile.base, Dockerfile.postgres, Dockerfile.static, Dockerfile.static-py
      docker-compose.yml
      entrypoint.sh           # 613 lines of init + run fusion
      install_app.py          # string-mangles pyproject.toml + settings.py
      settings_docker.py      # bind-mounted onto quartz/settings_local.py
      init-unix.sql
      Makefile, act.py, project.yml
```

After migration the whole `docker/` directory is gone. The toolkit ships the Dockerfile and compose files as Python package data; the project carries only its own source, `apps.yaml`, `pyproject.toml`, and `.env`.

## Step-by-step

### 1. Scaffold toolkit files into the project

From the project root:

```
arches-toolkit init <project-name> --target-dir . --force
```

This is idempotent and non-destructive:

- Appends an `# arches-toolkit:env-overrides` block to `<package>/settings.py` (DB/ES/Celery hosts from env vars).
- Writes `.env` with `PROJECT_NAME`, `DJANGO_SETTINGS_MODULE=<package>.settings`, `WSGI_APP`, `CELERY_APP`, default DB creds.
- Writes `.dockerignore`.
- Appends toolkit-related entries to `.gitignore`.

It does **not** touch anything under `docker/`.

### 2. Declare external Arches apps in `apps.yaml`

For every external Arches app listed in `INSTALLED_APPS` that isn't built in to core Arches:

```
arches-toolkit add-app arches-controlled-lists --source pypi
arches-toolkit add-app arches-querysets        --source pypi
arches-toolkit add-app arches-component-lab    --source pypi
arches-toolkit add-app arches-her              --source git --repo https://github.com/archesproject/arches-her.git --ref dev/2.0.x
```

Non-Arches third-party Django apps (e.g. `grafana-django-saml2-auth`) stay in `pyproject.toml` dependencies — they're not toolkit-managed.

### 3. Sync the manifest into pyproject.toml

```
arches-toolkit sync-apps
```

This:

- Adds each `release` entry to `[project.dependencies]`.
- Tracks managed entries under `[tool.arches-toolkit] managed_apps`, so subsequent edits to `apps.yaml` stay idempotent.
- For git-sourced entries, writes the full `package @ git+url@ref` form.
- Canonicalises names (PEP 503), so pre-existing hand-written `arches_controlled_lists` + new managed `arches-controlled-lists` de-duplicate correctly.
- Generates `compose.apps.yaml` when any entry is in `develop` mode (no-op otherwise).

### 4. Delete the legacy `docker/` tree

```
rm -rf docker Makefile
```

(Keep `quartz/settings.py` — the toolkit's env-overrides were appended, not written fresh. The `try: from .settings_local import *` import at the bottom becomes a no-op once `settings_docker.py` is gone; leave it or remove it, your call.)

### 5. First build + boot

```
arches-toolkit dev --build
```

Brings up `db`, `elasticsearch`, `rabbitmq`, `cantaloupe`, `init`, `web`, `worker`, `api`, `webpack`. Baseline + dev overlay compose files come from the toolkit; you didn't write either.

Subsequent runs: `arches-toolkit dev` (no `--build`).

### 6. First-time DB setup

The `init` service's dev-mode warm-start probe short-circuits when the DB already has migrations. On a fresh volume it runs `migrate` and `createcachetable` and then exits. If you want the full arches bootstrap (drop+rebuild DB, reseed indexes, install default system settings):

```
arches-toolkit setup-db --dev
```

### 7. Verification

```
curl -I http://localhost:8000/auth/
```

Expect `HTTP/1.1 200 OK`. Static asset bundling served by `webpack` on `:9000`; `web` serves Django on `:8000`; `:5678` is debugpy.

## Gotchas hit during the pilot

- **Project-name collision with the old stack.** Old docker-compose.yml and new compose.yaml both resolve to project name `quartz` (directory basename), so the old `quartz-arches-1` container keeps port 8000 bound. Either tear down the old stack first (`cd old/docker && docker compose down`) or set `COMPOSE_PROJECT_NAME=<something-else>` for the pilot.
- **`settings_docker.py` was bind-mounted onto `quartz/settings_local.py` by the old compose.** Once the old compose is gone, the `try: from .settings_local import *` in `quartz/settings.py` silently no-ops — OK to leave, OK to remove.
- **`DJANGO_SETTINGS_MODULE` flips** from `quartz.settings_local` (old bind-mount trick) to `quartz.settings` (set in `.env`). Any envs / CI that hard-coded the old module need updating.
- **`STATIC_ROOT=/static_root`** (quartz settings.py default) vs the toolkit's `/var/arches/static_root`. Set `STATIC_ROOT` in `.env` if you depend on the old path.
- **`INSTALL_DEFAULT_GRAPHS / INSTALL_DEFAULT_CONCEPTS`** — quartz's old compose set them to `False`. Toolkit leaves this to the project — add to `.env` if you want the same behaviour.
- **CI** — `docker/project.yml` (the GitHub Actions workflow template) is gone with the rest of `docker/`. Phase 2 of the toolkit is reusable workflows; until then, projects keep their own `.github/workflows/*.yml` (and it should target `toolkit` images instead of the old `Dockerfile`+`Dockerfile.static`+`Dockerfile.static-py` chain).
- **`pyOpenSSL` ≥ 24 breaks `pysaml2`.** Not a toolkit issue — it's a latent quartz dep pin problem that the old editable-install workflow happened to paper over. With `uv sync` pulling the freshest compatible versions, `pyOpenSSL 24+` drops `X509_V_FLAG_NOTIFY_POLICY` and `pysaml2` still references it. Pin `pyOpenSSL<24` (or upgrade `pysaml2` / `grafana-django-saml2-auth` if a newer release fixes it) in `pyproject.toml`.

## What stays in the project

- `quartz/` source (Python + templates + migrations + etc.)
- `package.json`, `webpack/`, `frontend_configuration/` — frontend build config is project-owned
- `pyproject.toml`, `apps.yaml`, `.env`, `.dockerignore`
- `tests/`, `cypress/`, `docs/`, `LICENSE`, `README.md`, `manage.py`
