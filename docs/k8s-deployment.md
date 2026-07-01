# Kubernetes deployment: dev → staging → production

**Status:** designed 2026-07-01, not implemented. This is the Phase 2
deployment spec. It maps the local-dev contract (the compose files, which
[docs/helm-migration-audit.md](helm-migration-audit.md) already treats as
canonical) onto a k8s topology, and defines the three environments a
project moves through. The chart itself lives in `helm-arches`, not here —
this doc is the contract the chart implements; the audit doc is the delta
from chart 0.0.19.

**Goals, in priority order:**

1. **Stability** — Arches must be production-ready: zero-downtime rollouts,
   no shared-state races, survivable pod restarts, backups.
2. **Speed** — of rollout (merge → live on staging in minutes), of pod boot
   (seconds, not the old entrypoint's minutes), and of CI builds (warm
   cache, small images).
3. **Parity** — one image contract across all three environments; local dev
   remains the inner loop and can exercise the exact prod artifact
   (`dev --mode prod`, already designed in TASKS.md).

## The translation in one table

Local dev already made the k8s-shaped decisions: single-writer init,
env-var-driven service endpoints, non-root UID 1000, writable paths off the
code tree. The compose files translate almost mechanically:

| Compose concept | k8s equivalent | Notes |
|---|---|---|
| `x-arches` anchor (one image, per-service `command`) | One Deployment per role (web / worker / api), same image, different `command` | Helm named template plays the anchor's role |
| `init` service, `restart: no`, `service_completed_successfully` gates | **Split three ways** — see next section | The single biggest structural change, and where the speed comes from |
| `depends_on: condition: service_healthy` | Readiness/liveness/startup probes + init Job gating | k8s has no cross-Deployment depends_on; probes + idempotent boot replace it |
| Named volumes for `/var/arches/*` | Mostly **eliminated at build time**; `uploadedfiles` is the one real PVC/bucket | See storage section |
| `db` / `elasticsearch` / `rabbitmq` / `cantaloupe` services | Per-environment backing services | In-cluster for staging, managed/dedicated for prod |
| `.env` | ConfigMap + SOPS-encrypted Secrets | Existing fluxcd-repo pattern, unchanged |
| `COMPOSE_PROFILES` service toggles (designed) | values.yaml enables (`cantaloupe.enabled`, `api.enabled`, …) | Same topology knobs, same defaults |
| webpack dev server, debugpy, bind mounts | **Nothing** | Dev-overlay-only; never reaches a cluster |

## The init split — the key structural translation

Compose's `init` service conflates three different lifecycles because
compose only has "runs before the others". k8s forces the split, and each
piece lands where it runs fastest:

| Lifecycle | Runs | Contents | Mechanism |
|---|---|---|---|
| **Per image** | CI, once per build | webpack production build, `collectstatic`, frontend_configuration generation (see gap 4) | Dockerfile stages; output baked into `prod` + `nginx` targets |
| **Per release** | Once per deploy/upgrade | `migrate` → `createcachetable` → `es setup_indexes` → graph-guarded System Settings seed | k8s **Job** (Helm pre-upgrade/pre-install hook; helm-controller runs hooks, so Flux-triggered upgrades get it for free) |
| **Per pod** | Pod start | Nothing, if build-time generation of frontend_configuration holds; else regen into an `emptyDir` | initContainer — fallback only |

Two properties of the existing design carry over verbatim and are what
make this safe:

- **Idempotent bootstrap (resolved 2026-06-27).** Every init step is safe
  to re-run: `migrate` no-ops when current, `createcachetable` creates only
  if absent, `es setup_indexes` swallows index-exists 400s, the System
  Settings seed is graph-guarded. So the release Job can run on *every*
  Helm upgrade — including Flux image-automation bumps — with no cold/warm
  probe, and a Job that dies partway self-heals on the next release
  instead of stranding the DB.
- **Single writer.** Only the Job touches DB schema / ES indexes / seed
  data. Web/worker/api pods never mutate shared state at boot — which is
  precisely what lets them scale horizontally and roll without ordering
  constraints beyond "Job first".

Why collectstatic moves to build time: it is a pure function of the image
contents (installed apps + webpack output), so running it per-release is
wasted minutes on *every* rollout **and** it forces a ReadWriteMany
`static_root` PVC so nginx can see the output. Baking it removes both.
The audit doc already prefers this (option 1, "bake nginx image"); this
doc confirms it as the decision.

## Image-contract gaps to close first (blockers, all in this repo)

The `prod` target boots and serves HTTP 200 (Stage 3.2), but the frontend
asset pipeline through `frontend` → `prod` / `nginx` is unvalidated
against a real Arches webpack build. Ordered fixes:

1. **`frontend` stage script + output paths.** The stage runs `npm run
   build` and the `prod`/`nginx` targets copy `/app/dist`. Real Arches
   projects (scaffolded by `arches-admin`) expose `build_production` (dev
   uses `npm run start`, as our webpack service does), and emit
   `webpack/webpack-stats.json` + a build directory under the project tree
   — nothing writes `dist/`. Fix the script name and copy paths; validate
   against the quartz pilot. (Exact per-arches-line script/paths belong to
   the version-keyed recipe cascade if 7.6 differs from 8.x.)
2. **`webpack-stats.json` into `prod`.** Already a README "what's left"
   item. `django-webpack-loader` reads it to render every template — a
   prod image without it 500s on first page load. Copy from the `frontend`
   stage; must record `"status": "done"`.
3. **`nginx` target correctness.** `location /static/` aliases
   `/var/arches/static_root/`, which does not exist in the nginx image —
   bake the build-time collectstatic output in instead. `location /media/`
   aliases the webpack dist — wrong content entirely; media is
   `uploadedfiles` (serve via the web app / object storage, or mount the
   uploads volume read-only — decide per storage backend, below).
4. **frontend_configuration at build time.** `generate_frontend_configuration`
   derives from settings + installed apps, not from data — it *should* be
   runnable in the `prod` stage (with dummy DB env vars, since
   `django.setup()` connects lazily). Verify; if Django app-ready hooks
   force a DB round-trip, fall back to the per-pod initContainer +
   `emptyDir` (still cheap, still removes the shared volume). Either way
   `ARCHES_FRONTEND_CONFIGURATION_DIR` stays authoritative — this is what
   the Stage 6 patch exists for.
5. **Parameterise gunicorn.** `--workers 3` is hardcoded in the CMD and in
   compose. Read `GUNICORN_CMD_ARGS` / explicit `WEB_CONCURRENCY`-style env
   (workers, threads, `--timeout`, `--access-logfile -`) so the chart tunes
   per-environment without a new image.
6. **Health endpoint.** Probes need an auth-free, DB-cheap URL. Confirm
   what the current chart probes (it must probe *something* today); if
   Arches ships nothing suitable, add a trivial `/_health/` view to the
   project `urls.py` template — liveness returns 200 unconditionally,
   readiness may touch the DB connection.
7. **Logs to stdout.** k8s convention; drop the `logs` volume from the prod
   contract and make the settings template log to stderr/stdout when
   `ARCHES_LOG_TO_STDOUT` (or simply when not DEBUG). The compose `logs`
   volume stays for dev only.

Exit criterion for this block: the run-mode selector (`dev --mode prod`,
already designed) brings up `compose.yaml` alone — gunicorn, baked assets,
no webpack container, `readOnlyRootFilesystem`-compatible mounts — and
serves a fully-rendered page. That same gate is then the local
reproduction environment for any k8s incident.

## Runtime topology

Per project namespace (matches the existing per-project fluxcd namespaces):

- **web** — Deployment, ≥2 replicas in prod, HPA on CPU (later: RPS). The
  only user-facing Django surface.
- **api** — optional Deployment (values-gated), same image, port 8001
  command. Most projects don't split it; default off.
- **worker** — Deployment, celery. Replicas per queue depth (KEDA is a
  later optimisation, not Phase 2). `terminationGracePeriodSeconds` sized
  to the longest task; celery `--soft-time-limit` below it.
- **static** — Deployment from the project's `nginx` target image. Serves
  `/static/` from baked assets with the existing 7d expires; proxies
  nothing in k8s (Ingress does the routing — the baked `proxy_pass
  http://web:8000` default is compose-shaped; the chart overrides the
  config or the Ingress routes `/static/` straight to it).
- **init Job** — per release, as above. Helm hook
  (`pre-install,pre-upgrade`, `hook-delete-policy: before-hook-creation`)
  so failed migrations block the rollout *before* new pods start.
- **cantaloupe** — optional Deployment (values-gated, default per project
  — profile parity with compose).
- Ingress: `/static/` → static Service, everything else → web Service.
  `client_max_body_size`-equivalent annotation for uploads.

**Security context (all Arches pods):** `runAsUser: 1000`,
`runAsNonRoot: true`, `readOnlyRootFilesystem: true`, `emptyDir` at `/tmp`.
The writable-paths work (Stage 6 + `/var/arches`) was done precisely to
make this line achievable — turn it on from day one in the new chart, per
the audit's hardening step, so it never regresses.

**Probes:** startupProbe generous (Django `app.ready()` on Arches is
10–30s; budget 90s), readiness on the health URL every 10s, liveness
lazy (30s+, unconditional-200 URL) so a slow DB doesn't self-inflict
restarts. Worker: celery `inspect ping` or a liveness file touch.

**Zero-downtime invariants:** `RollingUpdate` with `maxUnavailable: 0`;
PodDisruptionBudget `minAvailable: 1` on web; and the policy that
**migrations must be backwards-compatible with the previous release**
(old pods keep serving while the Job migrates — expand/contract, never
drop-and-rename in one release). That policy is documentation + review
discipline, not tooling; write it into the project CI docs.

## Storage

| Path | Local dev | k8s |
|---|---|---|
| `frontend_configuration` | named volume, init writes | **none** (baked) or per-pod `emptyDir` (fallback) |
| `static_root` | named volume | **none** — baked into `nginx` image |
| `logs` | named volume | **none** — stdout |
| `uploadedfiles` | named volume | the one real state: RWX PVC baseline → object storage target |

`uploadedfiles` is shared by web (writes), worker (reads/writes), and
cantaloupe (reads). Two supported backends:

1. **RWX PVC** (baseline, what the old chart's `pvc-uploadedfiles.yaml`
   does). Works everywhere an RWX class exists; keep as default for
   continuity.
2. **Object storage via django-storages / S3-compatible** (target for
   prod). Pods go fully stateless, uploads survive anything, cantaloupe
   reads via its S3/HTTP source. Opt-in per project through settings env;
   not a blocker for the first chart cut.

Postgres and ES data are the backing services' problem, not the app
chart's (below).

## Backing services per environment

`settings.py` already reads `PGHOST` / `ESHOST` / `RABBITMQ_URL` /
`CANTALOUPE_HTTP_ENDPOINT` from env, so "bundled vs external" is pure
configuration — the same slot model as the compose profiles proposal.

| Service | dev (local compose) | staging | production |
|---|---|---|---|
| Postgres | postgis container, fsync off | in-cluster (existing Bitnami subchart / CNPG), small, PVC | managed PostGIS-capable instance **or** CNPG with HA + WAL backups |
| Elasticsearch | single node, 1g heap | single node, PVC | dedicated ES (or opensearch-compatible per upstream direction) with real heap/storage sizing; DR = `es reindex_database` from PG, so treat ES as rebuildable, PG as the source of truth |
| RabbitMQ | single container | in-cluster subchart | in-cluster HA pair or managed AMQP |
| Cantaloupe | container | container | container; source per uploads backend |

Guidance, not mandate: staging's job is to be *shaped* like prod cheaply
(same chart, same topology toggles), not to match its capacity. The
Bitnami-subchart wiring in chart 0.0.19 is explicitly out of the toolkit's
scope (audit doc) — carry it forward, fix only the credential plumbing the
audit flags (RABBITMQ_URL naming, PGUSER rename).

## Environments and promotion

The existing Flux + SOPS + image-automation + two-repo pipeline is
preserved by design (PLAN principle 3). The toolkit's contribution is the
artifacts and the tag scheme:

| Environment | What runs | Image tag | Who moves it |
|---|---|---|---|
| **dev (local)** | `arches-toolkit dev` (compose) | `dev` target, local build | the developer; `--mode prod` for parity checks |
| **staging** | k8s, project namespace | `main-<build-id>` from `project-ci.yml` on every merge to main | Flux ImagePolicy tracks `main-*` → auto-rollout, minutes after merge |
| **production** | k8s, project namespace | `vX.Y.Z` from `project-release.yml` on tag push | semver bump lands as a reviewable commit in the fluxcd repo (existing pattern) |

Pinning discipline:

- **Base image:** projects deploying to prod pin
  `<toolkit-sha>-arches-stable-8.1.x` (or better, the digest) in `.env` /
  CI args. Floating `latest-arches-*` tags are for local dev only.
- **Apps:** `switch-mode <app> release` before promoting to production
  (per the npm-deps design: develop-mode deploys are SHA-locked branch
  tips — acceptable on staging, not on prod).
- **Recipe:** the per-project recipe pin (designed in TASKS.md) is what
  makes "same git commit → same image" hold across CI runners.

`project-ci.yml` (reusable workflow, Phase 2 item) builds `prod` +
`nginx` targets, Trivy-scans, SBOMs, pushes both with the `main-<bid>`
tag — mirroring `base-image.yml`, which already establishes the pattern
(scan gates on HIGH/CRITICAL, cosign scaffolded until action-pinning is
resolved).

## Speed budget

Where the time goes today (old toolkit) and where it goes after:

| Stage | Old | Target | How |
|---|---|---|---|
| CI image build (warm) | 10–20 min | **2–5 min** | base image prebuilt (rarely changes); BuildKit cache mounts don't persist on GHA runners, so `project-ci.yml` must add `--cache-from/--cache-to type=registry` (or `type=gha`) — without this the uv/npm cache mounts silently do nothing in CI |
| merge → staging live | manual / tens of minutes | **< 10 min** | Flux image automation + the small init Job |
| init per rollout | minutes (migrations + npm + collectstatic every start) | **seconds when no-op** | build-time baking; Job runs only migrate/cachetable/indexes/seed-guard, all no-ops on a settled DB |
| pod boot | minutes | **10–30 s** | no entrypoint bootstrap; gunicorn starts straight into a prebuilt venv + baked assets; startupProbe absorbs `app.ready()` |
| static requests | Django/whitenoise-ish through gunicorn | nginx with 7d cache headers | `nginx` target; CDN in front is a values-level concern later |
| runtime DB | new conn per request | pooled | `CONN_MAX_AGE` in settings template now; pgbouncer/CNPG pooler when a project actually needs it |

Rollback speed is part of the budget: because migrations are
backwards-compatible by policy, rolling back = Flux/Helm revert to the
previous image tag, no down-migration, seconds.

## Production-readiness checklist (chart 0.1.0 acceptance)

- [ ] init Job runs as Helm hook; failed migrate blocks rollout, pods keep serving old release
- [ ] web ≥2 replicas rolls with `maxUnavailable: 0` and zero 5xx during deploy (test with load)
- [ ] all Arches pods: non-root 1000, `readOnlyRootFilesystem: true`
- [ ] pod restart loses nothing: uploads on PVC/bucket, no writes outside `/var/arches` + `/tmp`
- [ ] probes: kill -9 a web pod under load → traffic unaffected; DB outage → readiness fails, no restart storm
- [ ] `es reindex_database` runbook tested — ES volume loss is a degraded-search incident, not data loss
- [ ] PG backup/restore runbook per environment (managed snapshots or CNPG barman)
- [ ] resource requests/limits set for web/worker/static/cantaloupe with starting numbers recorded in values
- [ ] logs on stdout, scraped by the cluster stack; DEBUG off; `ALLOWED_HOSTS`/CSRF origins from values
- [ ] staging namespace runs the identical chart with only values differing

## Where the work lands

| Repo | Work |
|---|---|
| **arches-toolkit** (this repo) | Image-contract gap list above; run-mode selector; `project-ci.yml` / `project-release.yml` reusable workflows with registry caching; this doc |
| **helm-arches** | Chart 0.1.0 breaking rewrite per the audit doc's sequence, implementing this topology; the exported `toolkit-adaptation-wip.patch` is the starting point |
| **fluxcd repos** | Per-project: ImagePolicy regex for the new tag shape, values for the new chart — the audit's "NOT in this audit" list stays untouched |

## Ordered execution plan

1. **Close the image-contract gaps** (this repo). Exit: prod image renders
   pages with baked assets. Blockers for everything below.
2. **Run-mode selector** (`dev --mode prod`, already designed). Exit: local
   prod-parity smoke test exists and is cheap to run.
3. **`project-ci.yml`** with registry cache + `main-<bid>` / semver tags.
   Exit: quartz pilot builds `prod` + `nginx` in CI under 5 min warm.
4. **Chart 0.1.0 spike** in a test namespace against the pilot image —
   audit doc's CRITICAL items + init Job + security contexts from day one.
   Exit: pods Ready, upload survives restart, deploy under load is clean.
5. **Staging namespace** with Flux image automation end-to-end. Exit:
   merge to pilot main → staging updated with no human step.
6. **Prod hardening**: S3 uploads option, HPA/PDB, backup + reindex
   runbooks, semver promotion of the pilot. Exit: checklist above green.
7. **Migrate remaining projects one at a time**, old chart pinned until
   each project's image is toolkit-built (audit doc's sequence).

## Rejected / deferred

- **Per-pod migrations in an initContainer on every web pod.** N pods race
  the same migrate; the single-writer invariant exists to prevent exactly
  this. One Job.
- **Keeping collectstatic at deploy time with a shared RWX static PVC.**
  Slower every rollout, RWX storage cost, and one more stateful thing;
  build-time baking is strictly better once gap 1–3 land.
- **WhiteNoise instead of the nginx target.** Viable zero-infra fallback
  (and fine for tiny deployments), but it puts static serving back on
  gunicorn workers; the nginx image is already in the contract. Revisit
  only if the extra Deployment proves annoying.
- **KEDA / queue-depth worker autoscaling, CDN, distroless, mandatory
  cosign** — real, later (Phase 3 hardening); nothing in this design
  blocks them.
- **In-toolkit Helm chart.** Already decided 2026-06-11 — charts live in
  `helm-arches`; the toolkit ships the contract (images + this spec), not
  the templates.
