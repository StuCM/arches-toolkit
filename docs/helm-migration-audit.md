# Helm chart audit: `helm-arches` vs arches-toolkit image contract

Audit of [/home/stuart/git/fat/helm-arches/archesproject/](../../helm-arches/archesproject/) (chart 0.0.19) against the arches-toolkit `prod` image contract.

**Live projects currently run on this chart.** Migration must be staged; items are ordered by severity.

## Bottom line

The chart is **fundamentally incompatible** — not an incremental patch. Every deployment (`web`, `worker`, `api`) calls `../entrypoint.sh <command>` via a script the new image doesn't ship. Env var names differ (`PGUSERNAME` vs `PGUSER`). Volume mounts for the four toolkit-required paths are entirely absent. Treat this as "chart 0.0.20 is a breaking rewrite", not a bump.

## Contract audit

| # | Point | Current | Fit | Needed |
|---|---|---|---|---|
| 1 | Image reference | `ghcr.io/flaxandteal/arches-base:docker-8.1.0-release` (values.yaml:20-22) | MISMATCH | Point at project image from toolkit `prod` target; separate image for the `nginx` target |
| 2 | Init container | `../entrypoint.sh run_migrations` (deployment-worker.yaml:41) | MISMATCH | `python manage.py migrate --noinput && createcachetable && collectstatic --noinput` — and make init a separate container/Job shared across pods (not just in worker) |
| 3 | Runtime commands | `../entrypoint.sh run_arches/run_celery/run_api` in all three deployments | MISMATCH | `gunicorn --bind 0.0.0.0:8000 --workers 3 ${WSGI_APP}` for web/api; `celery -A ${CELERY_APP} worker -l INFO` for worker |
| 4 | Volume mounts | None — no `volumes:` or `volumeMounts:` anywhere | MISMATCH | PVCs/emptyDirs for `/var/arches/frontend_configuration` (init RW → main RO), `/var/arches/uploadedfiles` (RWX), `/var/arches/static_root`, `/var/arches/logs` |
| 5 | Env var names | `PGUSERNAME`, `ARCHES_ROOT=/web_root/arches`, `STATIC_ROOT=/static_root` in configmap-env.yaml; no `WSGI_APP` / `CELERY_APP` / `ARCHES_FRONTEND_CONFIGURATION_DIR` / `ARCHES_UPLOADED_FILES_DIR` | PARTIAL | Rename `PGUSERNAME` → `PGUSER`; drop hard-coded `ARCHES_ROOT`; move `STATIC_ROOT` to `/var/arches/static_root`; add the four missing toolkit vars |
| 6 | Security context | Empty / commented-out in values.yaml:138-147 | MISMATCH | `runAsUser: 1000`, `runAsNonRoot: true`; `readOnlyRootFilesystem: true` is achievable once volumes land |

## Entry points the chart assumes exist (and don't, in toolkit images)

- `entrypoint.sh run_arches` — deployment.yaml:38
- `entrypoint.sh run_migrations` — deployment-worker.yaml:41
- `entrypoint.sh run_celery` — deployment-worker.yaml:77
- `entrypoint.sh run_api` — deployment-api.yaml:39

All gone. Must be replaced with direct `gunicorn` / `celery` / `python manage.py ...` invocations.

## Static asset serving

Today: a separate `deployment-static.yaml` using `flaxandteal/arches-static:5.0` on port 8080 — **does not share a PVC with the main app**, so collectstatic output is invisible to it.

Toolkit options:
1. **Bake nginx image.** Use the toolkit Dockerfile's `nginx` target to produce a project-specific static image. Chart gets a dedicated nginx deployment pointing at that image. Cleanest; matches Dockerfile as shipped.
2. **Shared PVC.** Main app's init container runs collectstatic into a `/var/arches/static_root` PVC; nginx deployment mounts that PVC read-only. Works, but requires ReadWriteMany.

(1) is preferred — it keeps the image/runtime split clean and avoids RWX storage costs.

## Configmap / secret structure

- **ConfigMap `<release>-env`** — holds most vars; needs renames + additions (see contract row 5)
- **Secret `<release>`** — only `celery-broker-url`. Sourced via `helpers.tpl` from `values.rabbitmq.auth.*`. Verify those keys exist in the Bitnami subchart values passed through. Rename to `RABBITMQ_URL` for toolkit consumption.
- **Secret `<release>-env`** — `DJANGO_SECRET_KEY` + freeform `secretEnv` dict. OK as-is.
- **PGPASSWORD** — correctly sourced from the PostgreSQL subchart's secret (deployment.yaml:56-60).

## Compose as a reference

[cli/src/arches_toolkit/_data/compose.yaml](../cli/src/arches_toolkit/_data/compose.yaml) is the canonical contract:

- Init command — lines 122-128
- Runtime commands — lines 131-140
- Volume mounts — lines 41-46
- Env var names — lines 19-30

Use it as the diff target when rewriting the chart templates.

## Risk register (migration order)

**CRITICAL — all pods CrashLoopBackOff without these:**
1. Replace `entrypoint.sh` calls across deployment.yaml / deployment-worker.yaml / deployment-api.yaml with direct commands.
2. Rename `PGUSERNAME` → `PGUSER` in configmap-env.yaml.
3. Add init container that runs `migrate + createcachetable + collectstatic`.
4. Add `WSGI_APP` / `CELERY_APP` to configmap-env.yaml.

**HIGH — data loss / runtime breakage:**

5. Add volume mounts for the four `/var/arches/*` paths.
6. Rework static serving (preferred: nginx-target image).
7. Remove hard-coded `ARCHES_ROOT=/web_root/arches` and `STATIC_ROOT=/static_root`.

**MEDIUM — hardening:**

8. Add `runAsUser: 1000`, `runAsNonRoot: true`, then `readOnlyRootFilesystem: true` once volumes verified.
9. Add `ARCHES_FRONTEND_CONFIGURATION_DIR` / `ARCHES_UPLOADED_FILES_DIR` — already set by the image but explicit chart-level defaults avoid surprises.
10. Verify Bitnami rabbitmq subchart exposes `auth.username` / `auth.password` the way `helpers.tpl` assumes.

## Suggested migration sequence

1. **Spike in a test namespace.** Build a toolkit image from the real quartz, deploy against a fork of chart 0.0.19 with the four CRITICAL items fixed. Verify pods reach Ready.
2. **Validate data path.** Port-forward / kubectl exec; check Django admin, upload a file, run a celery task.
3. **Add volume mounts.** Verify uploads and static assets survive pod restarts.
4. **Harden.** Security context → readOnlyRootFilesystem.
5. **Cut chart 0.1.0** (semver signal — breaking change; 0.0.x minor bump would be misleading given the scope).
6. **Migrate live projects one at a time**, pinning the old chart version in each project's HelmRelease until that project's image is also rebuilt from the toolkit.

## What's NOT in this audit

- Bitnami subchart values (`postgresql.*`, `elasticsearch.*`, `rabbitmq.*`) — unchanged, toolkit is image-layer only
- SOPS / ExternalSecrets wiring — unchanged
- Flux `ImagePolicy` tag regex — needs widening if toolkit CI emits a different tag shape (see PLAN.md Phase 2); separate work
- `make_arches_8.py` scaffolder — unchanged
