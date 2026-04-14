# Patches applied to upstream Arches

Each `*.patch` in this directory is applied by `docker/base/Dockerfile` via `git am` against the Arches source tree pinned by `ARCHES_REF`.

## Patch header requirements

Every patch must carry these headers inside its commit message (after `Subject:`):

```
Upstream: <URL of upstream PR, or "none yet">
Last-reviewed: YYYY-MM-DD
Reason: <one-line justification for why this patch exists>
```

No expiry field. Staleness is surfaced by the `patch-health` CI job, never by a failed build. Renewal is a single `arches-toolkit patch renew <name>` command that bumps `Last-reviewed`.

## Current patches

| File | Subject |
|---|---|
| `0001-frontend_configuration-honour-ARCHES_FRONTEND_CONFIG.patch` | Parameterise the `generate_frontend_configuration()` output directory via `ARCHES_FRONTEND_CONFIGURATION_DIR`, so containers can relocate that runtime-writable path onto a volume and run non-root with a read-only root filesystem. |

See `arches-toolkit patch list` for the live table including `Last-reviewed` ages and upstream PR state.

The fork inventory ([../../../docs/fork-inventory.md](../../../docs/fork-inventory.md)) concluded that zero patches carry forward from the existing F&T fork; this is the first *new* patch, created as the Stage 6 proof-of-concept for the patch workflow.
