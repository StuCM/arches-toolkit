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
