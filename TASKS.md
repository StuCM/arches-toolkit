# arches-toolkit — Phase 1 Tasks

Ordered work list for Phase 1 (local build + dev loop). Each task has acceptance criteria. Tasks within a stage can be parallelised where noted; stages themselves are roughly sequential because later stages depend on earlier ones.

See [PLAN.md](PLAN.md) for design context.

---

## Stage 0 — Foundation

### 0.1 — Initialise git repository
- [ ] `git init` in this directory
- [ ] First commit: initial scaffold (README, PLAN, TASKS, skeleton dirs)
- [ ] Push to `github.com/flaxandteal/arches-toolkit`
- [ ] Set branch protection on `main` (require PR, 1 review)

### 0.2 — License & metadata
- [ ] Decide license (suggest Apache 2.0 for consistency with Arches itself)
- [ ] Add `LICENSE` file
- [ ] Add `CODEOWNERS` (start minimal — primary maintainers)

### 0.3 — CI scaffolding
- [ ] `.github/workflows/ci.yml` — lints markdown, validates YAML, runs `hadolint` on any `Dockerfile` once present
- [ ] Acceptance: PR against main runs lint job and passes on empty tree

---

## Stage 1 — Fork inventory (blocks everything downstream)

### 1.1 — Catalogue the F&T fork
- [ ] Clone `flaxandteal/arches` branch `docker/8.1` to a scratch dir
- [ ] Run `git log --oneline archesproject/dev/8.1.x..HEAD` (or equivalent)
- [ ] Produce `docs/fork-inventory.md` with a table: commit sha, subject, author, date, first-pass classification

**Acceptance**: a reviewable document listing every divergent commit.

### 1.2 — Classify each commit
Classify into one of four buckets:

- **A — Upstreamable as-is**: clean fix, good commit message, no F&T-specific logic
- **B — Upstreamable with adaptation**: underlying idea upstream-worthy, needs refactor first
- **C — Permanently F&T-specific**: genuine divergence (licensing, branding, hard-coded F&T infra)
- **D — Obsolete**: dead code, superseded by upstream, no longer needed

**Acceptance**: every commit has a bucket and a one-line justification. Count per bucket recorded.

### 1.3 — Define the migration set
- [ ] Commits in A + B + C become patches under `docker/base/patches/`
- [ ] Commits in D are dropped
- [ ] Generate `docker/base/patches/*.patch` files from bucket A/B/C commits via `git format-patch`
- [ ] Add required headers manually to each: `Upstream:`, `Last-reviewed:`, `Reason:`

**Acceptance**: `docker/base/patches/` contains N files, each with complete header metadata. `docs/fork-inventory.md` records which commit maps to which patch.

### 1.4 — Submit upstream PRs for bucket A
- [ ] For each A patch, open an upstream PR against `archesproject/arches`
- [ ] Update patch headers with PR URLs

**Acceptance**: patch headers link to real PRs. Not blocking Phase 1 — these can merge on their own timeline.

---

## Stage 2 — Base image pipeline

### 2.1 — `docker/base/Dockerfile`
- [ ] Multi-stage: `arches-src` (git clone + `git am patches/`) → `base` (ubuntu + uv + venv + pip install arches)
- [ ] Build args: `ARCHES_REPO` (default archesproject/arches), `ARCHES_REF` (default `stable/8.1.0`)
- [ ] Use BuildKit cache mounts (`--mount=type=cache,target=/root/.cache/uv`)
- [ ] Non-root user `app:1000` in the `base` stage
- [ ] Writable paths (`/var/arches/frontend_configuration`, `/var/arches/uploadedfiles`) created with correct group ownership, declared as `VOLUME`s

**Acceptance**: `docker build -f docker/base/Dockerfile --target base .` succeeds locally, produces image under 500MB, runs `python -c "import arches; print(arches.__version__)"` successfully.

### 2.2 — `docker/base/build.sh`
- [ ] Thin wrapper: reads `ARCHES_REF` from env or flag, invokes `docker buildx build` with sensible defaults
- [ ] Supports `--publish` flag for CI to push
- [ ] Supports `--platform` for multi-arch (initially amd64 only)

**Acceptance**: `./build.sh` builds the image. `./build.sh --arches-ref master` builds against upstream master.

### 2.3 — CI workflow: base image build
- [ ] `.github/workflows/base-image.yml`
- [ ] Triggers: push to main that touches `docker/base/**`, weekly cron, `workflow_dispatch` with `arches_ref` input
- [ ] Matrix: pinned refs (e.g. `stable/8.1.0`) + floating refs (`master`)
- [ ] On success: push to `ghcr.io/flaxandteal/arches-toolkit:<toolkit-sha>-arches-<ref>` + `:latest-arches-<ref>` floating
- [ ] Trivy scan, syft SBOM, cosign sign (OIDC keyless)

**Acceptance**: merging a trivial change to `docker/base/` publishes a new image visible in GHCR.

### 2.4 — CI workflow: patch health check
- [ ] `.github/workflows/patch-health.yml`
- [ ] Weekly cron
- [ ] Reads patch headers, polls GitHub API for upstream PR state
- [ ] Posts summary as an issue comment on a pinned tracking issue, or as a job summary
- [ ] **Does not fail the workflow** — informational only

**Acceptance**: weekly report appears with per-patch status table.

---

## Stage 3 — Project Dockerfile (multi-target)

### 3.1 — `docker/project/Dockerfile`
- [ ] Stages: `frontend` (node:20-slim, npm build) → `build` (uv, python deps) → `dev` → `prod` → `nginx`
- [ ] `FROM ghcr.io/flaxandteal/arches-toolkit:latest-arches-<ARCHES_REF> AS base`
- [ ] BuildKit cache mounts for uv, npm, apt
- [ ] `.dockerignore` at repo root with node_modules, .git, tests, .venv
- [ ] Non-root UID 1000 in prod, writable paths via VOLUME declarations only

**Acceptance**:
- `docker build --target prod` produces image under 1.2 GB
- `docker build --target dev` works and contains debugpy
- Both succeed without re-downloading pip/npm caches between clean rebuilds on the same host

### 3.2 — Test against a real project
- [ ] Take a copy of `quartz/arches-quartz` into a scratch directory
- [ ] Replace its Dockerfile(s) with a thin `FROM arches-toolkit:... AS base` + project-specific bits
- [ ] Build `prod` target — succeeds, starts, serves HTTP 200

**Acceptance**: a real Arches project image produced from the new Dockerfile serves a request.

---

## Stage 4 — Compose files for local dev (THE big win)

### 4.1 — `docker/project/compose.yaml` (prod-like baseline)
- [ ] YAML anchors (`x-arches: &arches`) for shared config — web/worker/api share ~8 lines each
- [ ] `init` service with `restart: no` — runs migrations + collectstatic + frontend_configuration generation
- [ ] Main services `depends_on: init: { condition: service_completed_successfully }`
- [ ] db, elasticsearch, rabbitmq, cantaloupe services unchanged in shape from current
- [ ] Writable paths (`frontend_configuration`, `uploadedfiles`) declared as named volumes

**Acceptance**: `docker compose up` brings up the full stack; init exits cleanly; web serves HTTP 200; restart of web takes <5 seconds (not 2 minutes).

### 4.2 — `docker/project/compose.dev.yaml` (dev overlay)
- [ ] Bind mounts: project source, arches source (optional for core dev), arches_apps
- [ ] Named volume `venv:/venv`
- [ ] `develop.watch` rules — `sync` for code paths, `rebuild` for `pyproject.toml`
- [ ] Exposed ports: `:8000` (web), `:9000` (webpack devserver), `:5678` (debugpy)
- [ ] Dev command: `python manage.py runserver 0.0.0.0:8000` instead of gunicorn

**Acceptance**:
- `docker compose -f compose.yaml -f compose.dev.yaml up --watch` works
- Editing a `.py` file reloads Django within 1-2 seconds without container restart
- Editing `pyproject.toml` + running `docker compose exec web uv sync` installs new deps in <5 seconds with no rebuild

### 4.3 — `compose.extras.yaml` auto-discovery hook
- [ ] Convention: if `compose.extras.yaml` exists in the project, `arches-toolkit dev` auto-loads it
- [ ] Document the convention in `docs/compose-extras.md`

**Acceptance**: a project with an extra service (e.g. second cantaloupe) can add it without modifying the toolkit.

### 4.4 — Document the dev workflow
- [ ] `docs/local-dev.md` — step-by-step "from zero to running" including the `uv sync` dep flow
- [ ] Compare to old workflow so users see the time savings
- [ ] Troubleshooting section for common issues (permissions, ports, volume cache)

**Acceptance**: a dev who has never seen the toolkit can go from `git clone` to running Arches in under 10 minutes following only `docs/local-dev.md`.

---

## Stage 5 — CLI (minimum viable)

### 5.1 — `cli/` package skeleton
- [ ] `pyproject.toml` using `uv` / setuptools, entry point `arches-toolkit`
- [ ] Framework: `typer` (cleaner than argparse for this size)
- [ ] Basic `--version` and `--help`
- [ ] Published to PyPI under `arches-toolkit` (reserve name early)

**Acceptance**: `uvx arches-toolkit --version` works from a clean machine.

### 5.2 — `arches-toolkit add-app <package>`
- [ ] Appends entry to `apps.yaml`
- [ ] Supports `--source pypi|git`, `--ref`, `--mode release|develop`
- [ ] Idempotent (no-op if already present)
- [ ] Prints next steps: `uv sync`, INSTALLED_APPS line, URL include

**Acceptance**: running the command twice produces no duplicate entries; running it against a fresh project produces a valid `apps.yaml`.

### 5.3 — `arches-toolkit sync-apps`
- [ ] Reads `apps.yaml`
- [ ] For release entries: appends to `pyproject.toml` `[project.dependencies]`
- [ ] For develop entries: writes `compose.apps.yaml` with bind mounts + editable installs
- [ ] Idempotent

**Acceptance**: after `add-app` + `sync-apps` + `uv sync`, the app is importable in the web container.

### 5.4 — `arches-toolkit dev`
- [ ] Wrapper that runs `docker compose -f compose.yaml -f compose.dev.yaml [-f compose.apps.yaml] [-f compose.extras.yaml] up --watch`
- [ ] Only includes files that exist
- [ ] Passes through unknown flags to `docker compose`

**Acceptance**: `arches-toolkit dev` starts the stack with watch mode; `arches-toolkit dev --build` rebuilds.

### 5.5 — `arches-toolkit patch list` / `patch renew`
- [ ] `patch list` — prints table of patch files with header metadata (Upstream, Last-reviewed, days since review)
- [ ] `patch renew <name>` — updates `Last-reviewed:` in the specified patch header
- [ ] `patch status` — queries GitHub API for upstream PR state of each patch (requires `GH_TOKEN`)

**Acceptance**: commands produce correct output against the patch set from Stage 1.

---

## Stage 6 — First patch: `frontend_configuration` env var

Concrete proof-of-concept for the patch workflow. Solves the non-root-write problem.

### 6.1 — Write the patch
- [ ] Modify `arches/apps.py` to read `ARCHES_FRONTEND_CONFIGURATION_DIR` env var
- [ ] Default to current path for backward compat
- [ ] Commit message includes rationale and before/after

**Acceptance**: patch applies cleanly to `stable/8.1.0` via `git am`; Arches starts with and without the env var.

### 6.2 — Add to `docker/base/patches/`
- [ ] Export via `git format-patch`
- [ ] Fill in header: `Upstream:`, `Last-reviewed:`, `Reason:`

**Acceptance**: `arches-toolkit patch list` shows the new patch correctly.

### 6.3 — Submit upstream PR
- [ ] Open PR against `archesproject/arches`
- [ ] Update patch header with PR URL

**Acceptance**: PR exists; patch header links to it.

### 6.4 — Wire env var through compose + base Dockerfile
- [ ] `docker/project/compose.yaml` sets `ARCHES_FRONTEND_CONFIGURATION_DIR=/var/arches/frontend_configuration`
- [ ] `init` service generates into that path
- [ ] Web/worker mount the volume read-only

**Acceptance**: container runs as non-root in dev; k8s pod can run with `readOnlyRootFilesystem: true` (verified later, Phase 2).

---

## Stage 7 — Pilot project migration

### 7.1 — Choose pilot
- [ ] Pick a small, actively-developed Arches project (not quartz)
- [ ] Confirm owner has time to work through breakage with us

**Acceptance**: named pilot project with committed owner.

### 7.2 — Migrate
- [ ] Create a branch in the pilot repo
- [ ] Replace its Dockerfile(s) with the new thin overlay
- [ ] Replace `install_app.py` usage with `apps.yaml` + CLI
- [ ] Adopt `compose.yaml` + `compose.dev.yaml` from toolkit
- [ ] Remove Makefile (or reduce to a justfile with 3-4 shortcuts)

**Acceptance**: pilot project runs locally via `arches-toolkit dev`; all existing functionality preserved.

### 7.3 — Document migration steps
- [ ] `docs/migrating-a-project.md` — step-by-step using the pilot as worked example

**Acceptance**: another project owner could follow the doc start-to-finish.

### 7.4 — Feedback loop
- [ ] Collect pain points hit during pilot migration
- [ ] File issues for each
- [ ] Triage: fix in Phase 1 vs defer to Phase 2

**Acceptance**: backlog reflects real pilot-learned issues, not speculative ones.

---

## Design decision: pyproject/lockfile version skew vs base-image arches

**Status:** resolved — base-image-authoritative, enforced.

The project Dockerfile runs `uv sync --frozen --no-install-project
--no-install-package arches`. Excluding `arches` from the sync keeps the
patched editable install at `/opt/arches` (placed there by the base image)
intact; without the exclusion, uv reconciles the env to `uv.lock` and
replaces the editable install with the lockfile's PyPI version, orphaning
`/opt/arches` and losing the patches at runtime.

Build-time check: the Dockerfile compares `arches.__version__` from the
base image against the `arches` version pinned in `uv.lock` and emits a
warning if they diverge. Base wins at runtime; the warning surfaces drift
so users know to rebuild the base image (`docker/base/build.sh
--arches-ref <version>`) or accept the skew.

Ecosystem packages (`arches-querysets`, `arches-controlled-lists`, etc.)
are *not* base-managed — they install from the project's lockfile, in
either release or develop mode per `apps.yaml`. Skew between those and
the base arches version is still possible (e.g. `arches-querysets` imports
`from arches import VERSION` which may be missing on older base refs);
the recommended response is to bump the base image ref.

---

## Open issue: web boots before webpack-stats.json exists (cold-start race)

**Status:** parked — only bites on first `arches-toolkit dev` from a clean
state, not on the steady-state HMR loop.

In dev, `web` inherits depends_on from `compose.yaml` (db/es/rabbitmq/init)
but not from the webpack service (dev-only, defined in `compose.dev.yaml`).
On a cold compose up, `web` can serve a request before webpack has emitted
`/app/webpack/webpack-stats.json`, producing a confusing
`Error reading … webpack-stats.json` from django-webpack-loader. A refresh
30-60s later works.

Why it's parked: once containers are up they stay up — HMR handles file
changes and you rarely restart. The race surfaces mostly on a new
contributor's first run.

Fix when revisited:

1. Add a healthcheck to the `webpack` service that confirms
   `webpack-stats.json` exists (`test -f /app/webpack/webpack-stats.json`),
   with generous retries to cover initial compile (1-2 min).
2. Redefine `web` (and `api`) `depends_on` in `compose.dev.yaml` to
   include `webpack: condition: service_healthy` plus the existing
   db/es/rabbitmq/init entries. Don't rely on cross-file depends_on merge
   semantics — they vary by compose version.

Cost: dev cold start gets ~30-60s slower before the page is reachable.
Worth it for the onboarding-moment clarity.

---

## Open design problem: ARCHES_SRC bind mount shadows base-image patches

**Status:** unresolved. Affects `arches-toolkit dev` with `ARCHES_SRC` set.

The `ARCHES_SRC` overlay (`compose.arches-src.yaml`) bind-mounts a host
clone of arches over `/opt/arches`. Because bind mounts replace directory
contents, the patches `docker/base/patches/*.patch` applied at base-image
build time are no longer visible at runtime — Python imports the host
clone's files, not the patched copy.

**Why it matters.** Anyone using ARCHES_SRC to live-edit arches loses any
toolkit patch that touches code they're editing. Patches authored *for*
the toolkit (e.g. the `frontend_configuration` env-var fix) silently
disappear, and behaviour drifts from the baked image. Easy to miss until
you observe a setting being ignored.

**Workaround today.** Manually apply patches in the host clone:

```sh
cd $ARCHES_SRC
git am /path/to/arches-toolkit/docker/base/patches/*.patch
```

Brittle: needs to be redone on every rebase, and `git am` fails noisily
on partial overlap.

**Options for a better answer:**

1. **Doc-only.** Document the contract: "ARCHES_SRC means *your* clone is
   authoritative; apply patches yourself." Cheapest. Relies on user
   discipline.
2. **Auto-apply at container start.** A startup hook runs `git apply
   --check` then `git am` against the bind-mounted source. Idempotent if
   already applied; fails fast if conflicting. Mutates the user's host
   clone, which is surprising.
3. **Patch overlay, not source overlay.** Don't bind-mount over
   `/opt/arches`; instead mount the host clone at `/opt/arches-host` and
   use a Python `.pth` shim that imports from the host clone but layers
   patched modules from the baked image where they exist. Cleanest
   semantics, fiddly to implement.
4. **Eliminate patches.** Upstream every patch the toolkit carries so
   there's nothing to lose. The end goal but not on a near-term timeline.

Closely related to "pyproject/lockfile version skew" above — both ask
"who owns the runtime arches code." The base-image-authoritative model
is settled for the lockfile axis; this is the same question for the
bind-mount axis.

---

## Open design problem: scaffolded local-only apps

**Status:** unresolved. Needs a design session before picking an approach.

**Context.** `arches-toolkit create app my_thing` scaffolds a new Arches
application on disk. Before the user pushes it to git or publishes to PyPI,
there's no installable source — yet we'd like the app to "just work" in
the dev stack so newcomers can scaffold, edit, and iterate without git
ceremony up front.

**What we tried (and reverted):** a new `source: local` apps.yaml entry
that skipped pyproject and relied purely on a bind mount of the Python
package into `/venv/.../site-packages/<name>`. Arches 8.1's
`check_arches_compatibility` system check needs `importlib.metadata.requires(config.name)`
to succeed, which requires a real `.dist-info` directory. A bind-mounted
package has no `.dist-info`, so the check raises `PackageNotFoundError`
and the worker crashes at startup. Reverted in late Phase 1 pilot.

**Options on the table for a fix:**

1. **Install at runtime from bind-mounted path.** init service runs `uv pip
   install -e /opt/apps/<name>` on container start. Generates `.dist-info`,
   satisfies the check. Tried earlier in Phase 1 — has real issues with
   version skew between base image arches and project-locked arches,
   transitive dep resolution, and add/remove idempotency. Reverted to the
   overlay model. Would need careful redesign.
2. **Use `file://` URL in pyproject.toml** (`"arches-my-app @ file:///..."`)
   so uv sync installs with proper metadata. Works, but uv.lock then has
   absolute paths that don't transfer between machines — fragile for teams.
   Fine for solo dev.
3. **Use `[tool.uv.sources]` with a relative path** — uv supports
   `arches-my-app = { path = "../arches-my-app", editable = true }` which
   locks with a relative reference. Needs validation that uv handles this
   cleanly across machines, and we'd need to teach sync-apps to emit a
   separate [tool.uv.sources] table.
4. **Scaffold a local git repo on create** (`git init` + first commit)
   and use `source: git, repo: file:///path/to/repo.git`. A bit magical;
   leaves a git repo the user may not have wanted yet. But every machine's
   uv.lock would have a valid git+file:// URL.
5. **Generate fake `.dist-info` alongside the bind mount** so the metadata
   check passes. Hacky — we'd be forging package metadata to satisfy a
   runtime check.

**Constraint to consider.** Whatever we pick must keep teammates able to
clone the project and run `arches-toolkit dev` without unexpected manual
steps. Relative paths in uv.lock (option 3) might be the cleanest fit.

**Convenience to preserve.** `create app` should still auto-register in
apps.yaml — the user edits apps.yaml once, not once per propagation step.
Today that auto-registration uses `source: pypi` as a placeholder, and the
user has to fix the source before `sync-apps` will succeed.

---

## Phase 2 (deferred — not started in Phase 1)

- Helm chart improvements at `clusters/helm-arches`: volume provisioning for writable paths, security context defaults, `extraServices` map, chart bump to 0.0.19
- Reusable GitHub workflows for project CI (`project-ci.yml`, `project-release.yml`)
- Land `frontend_configuration` upstream and drop the patch once merged
- Expand CLI: `init`, `upgrade`, full `make_arches` unification
- Migrate remaining projects off the old toolkit

## Phase 3 (deferred)

- Security hardening: distroless variants, mandatory cosign, mandatory SBOM attestation
- Breaking-change upgrade migration tooling
- Supply chain (SLSA provenance)
- Deprecation and retirement of the old `arches-container-toolkit`

---

## Workflow notes

- Each stage roughly = one working week. Stages 1-4 are the critical path; 5-7 can start in parallel once 4 is stable.
- **Review gates**: end of Stages 2, 4, and 7 are natural points to stop and review with the wider team before proceeding.
- **Rollback plan**: nothing in Phase 1 touches production. The old toolkit keeps working throughout. Pilot project has its own branch. Safe to abandon at any stage.
