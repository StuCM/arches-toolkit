---
created: 2026-04-14
last-reviewed: 2026-04-14
fork: flaxandteal/arches @ docker/8.1
upstream-base: archesproject/arches @ dev/8.1.x
merge-base: 0ed5073974 (2026-04-14 at time of inventory)
---

# Arches fork inventory

Catalogue of commits on `flaxandteal/arches` branch `docker/8.1` that are absent from upstream `archesproject/arches` branch `dev/8.1.x`. Used to decide which divergences become maintained patches in [../docker/base/patches/](../docker/base/patches/) and which are obsoleted by the toolkit redesign.

## Bucket definitions

| Bucket | Meaning | Action |
|---|---|---|
| **A** | Upstreamable as-is — clean fix, no F&T-specific logic | Open upstream PR; include as patch only if the toolkit needs it before merge |
| **B** | Upstreamable with adaptation — idea is sound, needs refactor | Rework into a patch, submit upstream |
| **C** | Permanently F&T-specific — genuine divergence | Keep as maintained patch indefinitely |
| **D** | Obsolete — dead, superseded, or resolved by new architecture | Drop; do not patch |

## Commits (oldest first)

| SHA | Date | Subject | Files | Bucket | Justification |
|---|---|---|---|---|---|
| `0149f323c` | 2025-09-01 | fix(docker): ensure build works with newer versions | `Dockerfile`, `pyproject.toml` | **D** | The Dockerfile is replaced wholesale by [../docker/project/Dockerfile](../docker/project/Dockerfile). The `psycopg2 → psycopg2-binary` swap in `pyproject.toml` is handled at build time via a uv override, not a patch. |
| `03babc16b` | 2025-09-01 | ci(docker): add in docker base image builders | `.github/workflows/docker.yml`, `.github/workflows/postgres.yaml` | **D** | CI for building `flaxandteal/arches-base` and `flaxandteal/arches-postgis` moves into this toolkit repo under [../.github/workflows/](../.github/workflows/). Wrong repo to carry these workflows. |
| `95873a9da` | 2025-09-02 | fix(docker): ensure we can run in a read-only environment | `arches/apps.py` | **B → superseded** | Wraps `generate_frontend_configuration()` in a `try/except PermissionError`. Strict improvement possible: parameterise the output path via env var. Stage 6 lands that env-var patch; this workaround is not needed in the interim if Stage 6 ships alongside the base image. |
| `33288303f` | 2025-09-03 | fix(docker): build the deployment-ready docker image | `Dockerfile.postgres` | **D** | New postgis image: `FROM postgis/postgis:14-3.2 + init.sql`. Replaced by using upstream `postgis/postgis` directly with init.sql volume-mounted from the toolkit. Subject to confirmation of PLAN.md open question #2. |
| `de2eb42aa` | 2025-09-03 | fix(docker): build the deployment-ready postgis docker image | `.github/workflows/postgres.yaml` | **D** | Tweaks to the postgres CI workflow that is itself D. |
| `96abb7342` | 2025-09-06 | fix: postgis/postgis recent versions expect en-US.utf8 not C.UTF-8 | `arches/install/init-unix.sql` | **D** | Intermediate locale attempt, superseded within series by `195b4146f` then `2ae8efdaa`. |
| `195b4146f` | 2025-09-06 | fix: postgis/postgis recent versions expect en-US.utf8 not C.UTF-8 | `arches/install/init-unix.sql` | **D** | Superseded within series by `2ae8efdaa`. |
| `2ae8efdaa` | 2025-09-06 | fix: postgis/postgis recent versions expect en-US.utf8 not C.UTF-8 | `arches/install/init-unix.sql` | **D** | Superseded by `3522f63d0`. |
| `3522f63d0` | 2025-09-06 | fix: template_postgis in postgis/postgis image already has the database | `arches/install/init-unix.sql` | **A** | Clean upstream-worthy fix: `postgis/postgis` image ships with a `template_postgis` DB, so `CREATE DATABASE template_postgis` errors. Open an upstream PR. Not needed as a local patch because the toolkit ships its own init.sql (or a trimmed copy of Arches') volume-mounted into upstream postgis. |

**Author**: all 9 commits by Phil Weir (<phil.weir@flaxandteal.co.uk>) between 2025-09-01 and 2025-09-06.

## Bucket counts

| Bucket | Count |
|---|---|
| A — upstreamable as-is | 1 |
| B — upstreamable with adaptation (superseded by planned Stage 6 work) | 1 |
| C — F&T-permanent | 0 |
| D — obsolete / architectural-replacement | 7 |
| **Total divergent commits** | **9** |

## Implication for the toolkit

Zero patches need to be carried forward from the existing fork. The F&T fork is materially just the old Dockerfile/CI machinery — which is exactly what the toolkit redesign rebuilds. The one legitimate upstream fix (`3522f63d0`) targets a file the new architecture does not ship modified, so it becomes an upstream-only PR.

The one real patch the toolkit needs is **new**: the `ARCHES_FRONTEND_CONFIGURATION_DIR` env var (Stage 6 in [../TASKS.md](../TASKS.md)), which solves the non-root runtime write problem properly rather than swallowing `PermissionError` as `95873a9da` does.

This validates the redesign premise: the F&T divergence was almost entirely incidental to how the toolkit was packaged, not to Arches core behaviour.

## Action items

- Patches under [../docker/base/patches/](../docker/base/patches/): **none from this inventory**. The first patch ([`0001-frontend_configuration-honour-ARCHES_FRONTEND_CONFIG.patch`](../docker/base/patches/0001-frontend_configuration-honour-ARCHES_FRONTEND_CONFIG.patch)) was authored fresh in Stage 6 rather than carried over.
- Upstream PR queue: `3522f63d0` — `archesproject/arches` `arches/install/init-unix.sql`; plus the Stage 6 env-var patch once it's ready for submission.
- Fork retirement: once the toolkit ships and the pilot project (Stage 7) migrates, `flaxandteal/arches` `docker/8.1` can be archived.

## Other branches on the fork

- `origin/fat_dev/8.1.x` — inspected: **zero divergent commits** from `upstream/dev/8.1.x` at inventory time. No additional patch candidates. Safe to retire with the rest of the fork.
