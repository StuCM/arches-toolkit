# Project Dockerfile & compose files

Artefacts consumed by Arches project repositories via reusable GitHub workflow.

## Contents

- `Dockerfile` — single multi-target Dockerfile with stages `frontend` / `build` / `dev` / `prod` / `nginx`
- `.dockerignore` — sensible defaults for the project build context
- `compose.yaml` — production-like baseline, YAML-anchor shared config, init-container pattern
- `compose.dev.yaml` — dev overlay: bind mounts, venv volume, `develop.watch` rules, exposed debug ports

## How projects consume this Dockerfile

**Projects do not write their own Dockerfile.** Following the "Thin project layer" principle
(PLAN.md §Design principles), the toolkit's `docker/project/Dockerfile` is referenced directly
by the project's compose files.

A project repository contains only:

- `pyproject.toml` — deps, including `arches` and any apps
- `apps.yaml` — declarative app manifest (release + develop entries)
- `.env` — local secrets and project-specific settings (`DJANGO_SETTINGS_MODULE`, `WSGI_APP`, etc.)
- project source code (`<project>/settings.py`, `urls.py`, custom apps, templates, webpack config)
- optional `compose.extras.yaml` for project-specific sidecars
- optional `compose.apps.yaml` — *generated* by `arches-toolkit sync-apps`, not hand-edited

The `compose.yaml` and `compose.dev.yaml` shipped here reference the Dockerfile via
`build.context: .` with a `target:` selector (`prod` for the baseline, `dev` for the overlay).
They are either copied verbatim into the project repo by `arches-toolkit init` *or* (preferred)
consumed in-place via the CLI's `arches-toolkit dev` wrapper, which invokes:

```
docker compose \
  -f <toolkit>/docker/project/compose.yaml \
  -f <toolkit>/docker/project/compose.dev.yaml \
  [-f ./compose.apps.yaml] [-f ./compose.extras.yaml] \
  up --watch
```

The build context stays at the project root, so `COPY . /app` in the Dockerfile picks up
the project's code exactly as expected.

### Build args projects may want to pin

| Arg | Default | Purpose |
|---|---|---|
| `ARCHES_TOOLKIT_TAG` | `latest-arches-stable-8.1.0` | Base image tag. Pin to an immutable `vX.Y.Z-arches-<ref>` for reproducibility. |
| `PROJECT_NAME` | *(unset)* | Required. Used by the default `prod` CMD. |
| `PROJECT_PACKAGE` | falls back to `${PROJECT_NAME}` | The Python import path of the project's Django package. Set if it differs from `PROJECT_NAME`. |

### Overriding the Dockerfile (discouraged)

If a project genuinely needs a different build (e.g. additional apt packages baked into prod,
a non-Django entrypoint), the escape hatch is to add a short project-local Dockerfile that
does `FROM ghcr.io/flaxandteal/arches-toolkit:<tag> AS base` and layers its own changes on top.
Before reaching for this, consider whether a `compose.extras.yaml` service or a runtime-mounted
config would achieve the same outcome — the point of the toolkit is that projects stay thin.

## Known limitations (Phase 1)

- The base image has not yet been built and published to GHCR. This Dockerfile will not
  build end-to-end until Stage 2 CI lands. The Dockerfile is correct against the contract
  the base image will provide.
- `ARCHES_FRONTEND_CONFIGURATION_DIR` is not yet honoured by upstream Arches — Stage 6 of
  the plan ships the patch. The compose files declare the env var; the Dockerfile makes
  no attempt to work around the hardcoded path.

## See also

- [../../PLAN.md](../../PLAN.md)
- [../../TASKS.md#stage-3--project-dockerfile-multi-target](../../TASKS.md)
- [../../TASKS.md#stage-4--compose-files-for-local-dev-the-big-win](../../TASKS.md)
