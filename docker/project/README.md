# Project Dockerfile & compose files

Artefacts consumed by Arches project repositories via reusable GitHub workflow.

## Contents (to be written)

- `Dockerfile` — single multi-target Dockerfile with stages `frontend` / `build` / `dev` / `prod` / `nginx`
- `compose.yaml` — production-like baseline, YAML-anchor shared config, init-container pattern
- `compose.dev.yaml` — dev overlay: bind mounts, venv volume, `develop.watch` rules, exposed debug ports

## Usage (target state)

A project's Dockerfile becomes:

```dockerfile
ARG TOOLKIT_VERSION=v1.0.0
ARG ARCHES_REF=stable/8.1.0
FROM ghcr.io/flaxandteal/arches-toolkit:${TOOLKIT_VERSION}-arches-${ARCHES_REF} AS base
COPY . /app
RUN uv sync --frozen
```

Or, more commonly, the project calls the reusable workflow which uses this Dockerfile against the project's code directly.

## See also

- [../../PLAN.md](../../PLAN.md)
- [../../TASKS.md#stage-3--project-dockerfile-multi-target](../../TASKS.md)
- [../../TASKS.md#stage-4--compose-files-for-local-dev-the-big-win](../../TASKS.md)
