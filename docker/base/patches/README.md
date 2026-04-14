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

None yet.

The fork inventory ([../../../docs/fork-inventory.md](../../../docs/fork-inventory.md)) concluded that zero patches carry forward from the existing F&T fork. The first patch arrives via Stage 6 ([../../../TASKS.md](../../../TASKS.md)): `ARCHES_FRONTEND_CONFIGURATION_DIR` env var support, to allow the frontend configuration output path to move off the code tree onto a writable volume.
