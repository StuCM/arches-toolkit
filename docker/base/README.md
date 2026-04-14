# Base image pipeline

Builds `ghcr.io/flaxandteal/arches-toolkit:<toolkit-version>-arches-<arches-ref>` from official upstream Arches plus a reviewable patch series.

## Contents (to be written)

- `Dockerfile` — multi-stage build: clone upstream → apply patches → install via `uv`
- `build.sh` — thin wrapper for local builds
- `patches/` — `*.patch` files with metadata headers

## Patch format

Each patch file carries required headers:

```
Upstream: https://github.com/archesproject/arches/pull/NNNN
Last-reviewed: 2026-04-14
Reason: <one paragraph on why this patch exists>
```

CI enforces presence of these headers. `arches-toolkit patch renew` bumps `Last-reviewed:`.

## See also

- [../../PLAN.md](../../PLAN.md) — design rationale
- [../../TASKS.md#stage-2--base-image-pipeline](../../TASKS.md) — work items
