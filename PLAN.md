# arches-toolkit — Design Plan

This document captures the design decisions for rebuilding the Arches container toolkit. It is the authoritative reference; [TASKS.md](TASKS.md) turns it into executable work.

## Why

The current F&T container toolkit (`flaxandteal/arches-container-toolkit`) has accumulated pain points that block productive development and reliable deployment:

1. **Dependency changes require a full image rebuild** — the biggest daily friction. Adding a Python package means minutes of rebuilding, not seconds of `uv sync`.
2. **Five separate Dockerfiles** (`Dockerfile`, `Dockerfile.base`, `Dockerfile.static`, `Dockerfile.static-py`, `Dockerfile.postgres`) with overlapping concerns, unclear responsibilities, and no shared caching strategy.
3. **An opaque F&T fork of Arches** at `flaxandteal/arches` branch `docker/8.1`, from which `ghcr.io/flaxandteal/arches-base` is built. Changes are not reviewable at consumption time and drift accumulates without visibility.
4. **`install_app.py` is fragile** — regex-edits `settings.py`, `urls.py` and `pyproject.toml` to register Arches apps. Conflates "install for production use" with "clone for local development".
5. **Runtime-writable paths inside the code tree** (`frontend_configuration/`, `uploadedfiles/`) force containers to run as root and block read-only root filesystems in k8s.
6. **Three near-identical compose services** (web, worker, api) triplicating the same environment config.
7. **Slow cold restarts** — the entrypoint re-runs migrations, npm install, and asset builds on every container start.
8. **Docker-image size** — GDAL transitive deps, Node.js shipped to runtime, build tools not separated from runtime.

## Design principles

1. **Upstream first.** Where Arches core can reasonably be changed to remove a pain, prefer an upstream PR over a local patch. Patches exist for genuine F&T-specific needs and short-term shims, not as the first resort.
2. **Transparent layering.** Every file, image, and artefact consumed by a project should be readable in a public repository — no opaque published images with unreviewable contents.
3. **Preserve what works.** The existing cluster deployment pipeline (Flux + SOPS + image automation + two-repo pattern) is correct and will not be rewritten. The toolkit produces artefacts that consume into it.
4. **Lockstep versioning.** One repo, one release tag, all artefacts (image, chart, CLI, reusable workflows) versioned together. Projects pin one version and get consistent behaviour.
5. **Thin project layer.** Projects own their code, `pyproject.toml`, `apps.yaml`, and environment values. Everything else — Dockerfile, CI workflows, compose files, chart — comes from the toolkit and is upgraded centrally.
6. **Small, reviewable patch sets.** When patches against Arches core are necessary, they are small, env-var-shaped where possible, tagged with an upstream PR link, and reviewed regularly. Patch housekeeping never blocks project builds.

## Architecture

### Four concerns, one toolkit repo, three other repos

| Repo | Owns |
|---|---|
| `flaxandteal/arches-toolkit` (**this repo**) | Base image pipeline, project Dockerfile, Helm chart, reusable GitHub workflows, CLI, patches |
| `flaxandteal-arches/{project}` (×N) | Project code, `pyproject.toml`, `apps.yaml`, thin CI that calls toolkit reusable workflow |
| `bfc-fluxcd` / `quartz-fluxcd` (**existing, unchanged**) | HelmReleases, SOPS-encrypted values, namespace configs |
| `bfc-fluxcd-images` (**existing, unchanged**) | `$imagepolicy`-annotated ConfigMaps for Flux image automation |

### Base image pipeline

`docker/base/` builds a reusable base image from official Arches + a patch series.

```
FROM ubuntu:24.04 AS arches-src
ARG ARCHES_REF=stable/8.1.0     # tag, branch or sha — flexible
RUN git clone --depth 50 --branch ${ARCHES_REF} \
      https://github.com/archesproject/arches.git /src/arches
COPY patches/ /patches/
RUN if ls /patches/*.patch 2>/dev/null; then \
      cd /src/arches && git -c user.email=ci@local -c user.name=ci am /patches/*.patch; \
    fi

FROM ubuntu:24.04 AS base
# System deps (runtime only), uv, venv at /venv
COPY --from=arches-src /src/arches /opt/arches
RUN uv pip install --python /venv/bin/python /opt/arches
```

Published as `ghcr.io/flaxandteal/arches-toolkit:vX.Y.Z-arches-<ref>` with digests.

**Patch metadata**, enforced by CI:

```
Upstream: https://github.com/archesproject/arches/pull/NNNN
Last-reviewed: 2026-04-14
Reason: <why this patch exists>
```

No hard expiry. Weekly GitHub workflow polls upstream PR status and posts a status dashboard — never blocks builds. Only hard failure is `git am` conflict. Renewal is a single `arches-toolkit patch renew <name>` command.

### Project image — multi-target single Dockerfile

`docker/project/Dockerfile` has five targets:

| Target | Purpose | Includes |
|---|---|---|
| `frontend` | Webpack/npm build stage | node:20-slim, builds assets |
| `build` | Python dep install | `uv`, build tools, produces `/venv` |
| `dev` | Local development runtime | Dev tools, debugpy, non-root user; source mounted at runtime |
| `prod` | Production runtime | Slim, non-root, writable paths on volumes only, assets baked in |
| `nginx` | Static-serving sidecar (optional) | nginx:alpine + built assets |

Projects build `prod` for deployment and `dev` for local development. No separate `Dockerfile.static-py` / `Dockerfile.static` / `Dockerfile.base`.

### Local development loop

The single biggest user-facing change.

**`compose.yaml`** (published by toolkit, production-like baseline):
- `web`, `worker`, `api` services share config via YAML anchor (`x-arches: &arches`), ~8 lines each
- `db`, `elasticsearch`, `rabbitmq`, `cantaloupe` unchanged
- `init` service runs migrations + collectstatic + `frontend_configuration` generation **once** with `restart: no`; main services gate on `condition: service_completed_successfully`

**`compose.dev.yaml`** (overlay for dev):
- Bind mounts source + apps
- Named volume `venv:/venv`
- `develop.watch` rules: `sync` for code, `rebuild` for `pyproject.toml` changes
- Exposes `:9000` (webpack) and `:5678` (debugpy)

**Dependency flow**:
```
# Edit pyproject.toml
docker compose exec web uv sync     # ~1-3 seconds, venv updated in place
# Django autoreload picks it up, no restart
```

No rebuild, no volume nuke, no container restart. Prod images are unaffected (venv baked in at build time by CI).

### Runtime-writable paths

All writable paths move off the code tree onto named volumes:

| Path | Current (problem) | New |
|---|---|---|
| `frontend_configuration/` | Under code tree, requires root write | Named volume / k8s `emptyDir`, written by init container |
| `uploadedfiles/` | Under code tree | Named volume / PVC |
| `logs/` | Named volume already | Unchanged |
| `static_root/` | Named volume already | Unchanged |

Arches core hardcodes the `frontend_configuration` path in `arches/apps.py`. The **first patch in the patch series** parameterises it via env var `ARCHES_FRONTEND_CONFIGURATION_DIR` and is submitted upstream simultaneously. Proves the patch workflow and solves the permissions problem in one move.

### Applications (Arches plugins)

`apps.yaml` declares what applications the project uses:

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
    mode: develop              # bind-mount + editable install, dev only
```

**Release mode**: `arches-toolkit sync-apps` appends the package to `pyproject.toml` dependencies. `uv sync` installs. Reproducible, lockfile-pinned, no clone.

**Develop mode**: generates a `compose.apps.yaml` with a bind mount + editable-install rule for that app. Dev only; never in CI prod images.

**Registration**: projects continue to extend `ARCHES_INHERITED_APPS` in their own `settings.py` — the current pattern is already clean. The CLI does not generate a `_apps.py` file. `install_app.py`'s regex edits go away; adding an app is `arches-toolkit add-app <name>` which updates `apps.yaml` and prints a one-liner to add to `INSTALLED_APPS` if not already inherited.

### CLI

`arches-toolkit` (Python package, installed via `uvx arches-toolkit ...` or `pipx`):

| Command | Purpose |
|---|---|
| `init <name>` | Scaffolds a new project repo (runs `arches-admin startproject` in the toolkit container, overlays toolkit files) |
| `add-app <package>` | Adds to `apps.yaml`, suggests `INSTALLED_APPS` line |
| `sync-apps` | Rewrites `pyproject.toml` deps and `compose.apps.yaml` from `apps.yaml` |
| `dev` | `docker compose -f compose.yaml -f compose.dev.yaml up --watch` with auto-discovery of `compose.extras.yaml` |
| `patch list` | Lists all patches with upstream status |
| `patch renew <name>` | Bumps `Last-reviewed:` in patch header |
| `upgrade` | Bumps toolkit version, updates generated files |

Evolves `bfc-fluxcd/make_arches_8.py` rather than replacing it. The namespace-onboarding flow (GitHub repo creation, SOPS encryption, two-repo coordinated commits) is preserved and reused.

### Reusable GitHub workflows

Published by toolkit under `.github/workflows/`:

| Workflow | Purpose |
|---|---|
| `project-ci.yml` | Build + scan (trivy) + SBOM (syft) + sign (cosign) + push image with `main-<bid>` tag format for Flux automation |
| `project-release.yml` | On tag push, publishes semver-tagged images |

Projects consume as one-liners:

```yaml
jobs:
  ci:
    uses: flaxandteal/arches-toolkit/.github/workflows/project-ci.yml@v1
    with:
      arches_ref: stable/8.1.0
```

Upgrading project CI = bump `@v1` to `@v2`. No copy-pasted workflow drift across projects.

### What's deferred to Phase 2 / 3

- Helm chart improvements: volume provisioning for writable paths, security context defaults, `extraServices` map, bump to v0.0.19
- Deployment workflow (currently not needed — Flux image automation already handles rollouts)
- Security hardening beyond local dev: distroless variants, cosign signing made mandatory, full SBOM pipeline
- Upgrade migration tooling for breaking changes across major toolkit versions
- Unification of `make_arches.py` / `make_arches_8.py` / `make_buckram.sh` into one CLI

## Known open questions

1. **Fork inventory** — how many patches will survive classification? Determines if patch-over-upstream is sustainable long-term or if some other approach is needed.
2. **F&T postgis image** — does it do anything beyond init.sql? If not, switch to upstream `postgis/postgis:16-3.4` with init.sql volume-mounted.
3. **Which project is the Phase 1 pilot**? Should be small, representative, actively developed. Not quartz.
4. **Registry namespace**: publish toolkit images as `ghcr.io/flaxandteal/arches-toolkit`? Confirm.

## Phased delivery

| Phase | Scope | Ships |
|---|---|---|
| **1** (current) | Base image pipeline, project Dockerfile, local dev loop, CLI basics, pilot migration | Smaller images, painless dep install, app manifest, no fork, fast restarts |
| 2 | Helm chart improvements, reusable CI workflows, `frontend_configuration` patch landed upstream | Production-ready chart, clean project CI, cluster security posture improved |
| 3 | Security hardening, upgrade migration, full make_arches unification | Production-grade, multi-project rollout |

Phase 1 is independently valuable — if Phases 2 and 3 never happen, the dev loop transformation alone justifies the work.
