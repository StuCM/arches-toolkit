# arches-toolkit

Replacement for the Flax & Teal Arches container toolkit (`flaxandteal/arches-container-toolkit`).

Delivers:

- A single, modern multi-target Dockerfile for Arches projects (replaces five separate Dockerfiles today)
- A base image pipeline that builds from **upstream Arches + a reviewable patch series** — no long-lived fork
- A sharply faster local dev loop (`uv` + venv-in-volume + `docker compose watch`) where adding a dependency takes seconds, not minutes
- A small CLI (`arches-toolkit`) that replaces `install_app.py` and evolves `make_arches_8.py` into a unified tool
- Preserves and improves the existing Helm chart at `clusters/helm-arches` (Phase 2)

## Status

**Phase 1 in progress — local build + dev loop.** See [PLAN.md](PLAN.md) for the full design and [TASKS.md](TASKS.md) for the ordered work list.

## What this does NOT change

- The two-repo Flux pattern (cluster config + image config)
- SOPS-encrypted values in cluster repos (GPG on BFC, Azure KV on Quartz)
- Flux image automation (`$imagepolicy` ConfigMaps, `ImageUpdateAutomation`)
- Per-namespace folder structure in cluster repos
- The 4-deployment service topology (web, worker, api, static) + infra subcharts

The existing cluster deployment keeps working unchanged during Phase 1.

## Repository layout

```
arches-toolkit/
├── PLAN.md                    Design reference
├── TASKS.md                   Ordered work list
├── docker/
│   ├── base/                  Base image pipeline: upstream Arches + patches
│   │   ├── Dockerfile         (to be written)
│   │   ├── build.sh           (to be written)
│   │   └── patches/           *.patch files with upstream-link headers
│   └── project/               Multi-target Dockerfile for Arches projects
│       └── Dockerfile         (to be written)
├── cli/                       Python CLI package
├── chart/                     (Phase 2) Helm chart improvements
└── .github/workflows/         Reusable workflows for project repos
```

## Quick links

- [PLAN.md](PLAN.md) — design, architecture, rationale
- [TASKS.md](TASKS.md) — current work list with acceptance criteria

## Contributing

Not yet accepting external contributions — the toolkit is still being designed and the first pilot migration is pending. Once Phase 1 completes, contribution guidelines will be added.
