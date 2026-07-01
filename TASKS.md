# arches-toolkit — Phase 1 Tasks

Ordered work list for Phase 1 (local build + dev loop). Each task has acceptance criteria. Tasks within a stage can be parallelised where noted; stages themselves are roughly sequential because later stages depend on earlier ones.

See [PLAN.md](PLAN.md) for design context.

**Legend:** `[x]` done · `[~]` partial / superseded · `[ ]` outstanding. Status as of 2026-05-07; see commit history for the audit basis.

**Stage status snapshot**

| Stage | State | Outstanding |
|---|---|---|
| 0 — Foundation | partial | repo not pushed to GHE/GitHub; no LICENSE / CODEOWNERS; no `ci.yml` lint workflow |
| 1 — Fork inventory | done (modulo upstream PRs) | bucket-A upstream PRs not opened |
| 2 — Base image pipeline | done w/ caveats | base-image weekly cron not scheduled; cosign signing scaffolded but disabled |
| 3 — Project Dockerfile | done | (Dockerfile relocated under `cli/src/arches_toolkit/_data/`) |
| 4 — Compose for local dev | done | — |
| 5 — CLI | done | not yet on PyPI |
| 6 — `frontend_configuration` patch | done locally | upstream PR not yet opened |
| 7 — Pilot migration | partial | pilot is `arches-quartz` (not a small external project); Makefile not reduced; feedback-loop ticketing not done |

---

## Stage 0 — Foundation

### 0.1 — Initialise git repository
- [x] `git init` in this directory
- [x] First commit: initial scaffold (README, PLAN, TASKS, skeleton dirs)
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
- [x] Clone `flaxandteal/arches` branch `docker/8.1` to a scratch dir
- [x] Run `git log --oneline archesproject/dev/8.1.x..HEAD` (or equivalent)
- [x] Produce `docs/fork-inventory.md` with a table: commit sha, subject, author, date, first-pass classification

**Acceptance**: a reviewable document listing every divergent commit.

### 1.2 — Classify each commit
Classify into one of four buckets:

- **A — Upstreamable as-is**: clean fix, good commit message, no F&T-specific logic
- **B — Upstreamable with adaptation**: underlying idea upstream-worthy, needs refactor first
- **C — Permanently F&T-specific**: genuine divergence (licensing, branding, hard-coded F&T infra)
- **D — Obsolete**: dead code, superseded by upstream, no longer needed

**Acceptance**: every commit has a bucket and a one-line justification. Count per bucket recorded.

### 1.3 — Define the migration set
- [x] Commits in A + B + C become patches under `docker/base/patches/`
- [x] Commits in D are dropped
- [x] Generate `docker/base/patches/*.patch` files from bucket A/B/C commits via `git format-patch`
- [x] Add required headers manually to each: `Upstream:`, `Last-reviewed:`, `Reason:`

**Acceptance**: `docker/base/patches/` contains N files, each with complete header metadata. `docs/fork-inventory.md` records which commit maps to which patch.

### 1.4 — Submit upstream PRs for bucket A
- [ ] For each A patch, open an upstream PR against `archesproject/arches`
- [ ] Update patch headers with PR URLs

**Acceptance**: patch headers link to real PRs. Not blocking Phase 1 — these can merge on their own timeline.

---

## Stage 2 — Base image pipeline

### 2.1 — `docker/base/Dockerfile`
- [x] Multi-stage: `arches-src` (git clone + `git am patches/`) → `base` (debian-slim + uv + venv + pip install arches)
- [x] Build args: `ARCHES_REPO` (default archesproject/arches), `ARCHES_REF` (default `stable/8.1.0`)
- [x] Use BuildKit cache mounts (`--mount=type=cache,target=/root/.cache/uv`)
- [x] Non-root user `app:1000` in the `base` stage
- [x] Writable paths (`/var/arches/frontend_configuration`, `/var/arches/uploadedfiles`) created with correct group ownership, declared as `VOLUME`s

**Acceptance**: `docker build -f docker/base/Dockerfile --target base .` succeeds locally, produces image under 500MB, runs `python -c "import arches; print(arches.__version__)"` successfully.

### 2.2 — `docker/base/build.sh`
- [x] Thin wrapper: reads `ARCHES_REF` from env or flag, invokes `docker buildx build` with sensible defaults
- [x] Supports `--publish` flag for CI to push
- [x] Supports `--platform` for multi-arch (initially amd64 only)

**Acceptance**: `./build.sh` builds the image. `./build.sh --arches-ref master` builds against upstream master.

### 2.3 — CI workflow: base image build
- [x] `.github/workflows/base-image.yml`
- [~] Triggers: push to main that touches `docker/base/**`, weekly cron, `workflow_dispatch` with `arches_ref` input — push + dispatch wired; **no scheduled cron yet**
- [x] Matrix: pinned refs (e.g. `stable/8.1.0`) + floating refs (`dev/8.1.x`)
- [x] On success: push to `ghcr.io/flaxandteal/arches-toolkit:<toolkit-sha>-arches-<ref>` + `:latest-arches-<ref>` floating
- [~] Trivy scan, syft SBOM, cosign sign (OIDC keyless) — Trivy + SBOM live; **cosign scaffolded but commented out pending action SHA pinning**

**Acceptance**: merging a trivial change to `docker/base/` publishes a new image visible in GHCR.

### 2.4 — CI workflow: patch health check
- [x] `.github/workflows/patch-health.yml`
- [~] Weekly cron — actually monthly (1st of month, 05:23 UTC); revisit cadence if patch count grows
- [x] Reads patch headers, polls GitHub API for upstream PR state
- [x] Posts summary as an issue comment on a pinned tracking issue, or as a job summary — uses job summary
- [x] **Does not fail the workflow** — informational only

**Acceptance**: weekly report appears with per-patch status table.

---

## Stage 3 — Project Dockerfile (multi-target)

### 3.1 — `docker/project/Dockerfile`
- [x] Stages: `frontend` (node:20-slim, npm build) → `build` (uv, python deps) → `dev` → `prod` → `nginx` — relocated to [cli/src/arches_toolkit/_data/Dockerfile](cli/src/arches_toolkit/_data/Dockerfile) so the CLI ships it
- [x] `FROM ghcr.io/flaxandteal/arches-toolkit:latest-arches-<ARCHES_REF> AS base`
- [x] BuildKit cache mounts for uv, npm, apt
- [x] `.dockerignore` at repo root with node_modules, .git, tests, .venv
- [x] Non-root UID 1000 in prod, writable paths via VOLUME declarations only

**Acceptance**:
- `docker build --target prod` produces image under 1.2 GB
- `docker build --target dev` works and contains debugpy
- Both succeed without re-downloading pip/npm caches between clean rebuilds on the same host

### 3.2 — Test against a real project
- [x] Take a copy of `quartz/arches-quartz` into a scratch directory
- [x] Replace its Dockerfile(s) with a thin `FROM arches-toolkit:... AS base` + project-specific bits
- [x] Build `prod` target — succeeds, starts, serves HTTP 200

**Acceptance**: a real Arches project image produced from the new Dockerfile serves a request.

---

## Stage 4 — Compose files for local dev (THE big win)

### 4.1 — `docker/project/compose.yaml` (prod-like baseline)
- [x] YAML anchors (`x-arches: &arches`) for shared config — web/worker/api share ~8 lines each
- [x] `init` service with `restart: no` — runs migrations + collectstatic + frontend_configuration generation
- [x] Main services `depends_on: init: { condition: service_completed_successfully }`
- [x] db, elasticsearch, rabbitmq, cantaloupe services unchanged in shape from current
- [x] Writable paths (`frontend_configuration`, `uploadedfiles`) declared as named volumes

**Acceptance**: `docker compose up` brings up the full stack; init exits cleanly; web serves HTTP 200; restart of web takes <5 seconds (not 2 minutes).

### 4.2 — `docker/project/compose.dev.yaml` (dev overlay)
- [x] Bind mounts: project source, arches source (optional for core dev via `compose.arches-src.yaml`), arches_apps
- [x] Named volume `venv:/venv`
- [~] `develop.watch` rules — removed entirely 2026-06-11: compose watch refuses bind-mounted paths (the `.:/app` mount is the live-edit mechanism), so sync rules never did anything; rebuild-on-pyproject was wasted work (venv volume shadows the image's /venv) — `install` is the dep-change mechanism
- [x] Exposed ports: `:8000` (web), `:9000` (webpack devserver), `:5678` (debugpy)
- [x] Dev command: `python manage.py runserver 0.0.0.0:8000` instead of gunicorn

**Acceptance**:
- `docker compose -f compose.yaml -f compose.dev.yaml up --watch` works
- Editing a `.py` file reloads Django within 1-2 seconds without container restart
- Editing `pyproject.toml` + running `docker compose exec web uv sync` installs new deps in <5 seconds with no rebuild

### 4.3 — `compose.extras.yaml` auto-discovery hook
- [x] Convention: if `compose.extras.yaml` exists in the project, `arches-toolkit dev` auto-loads it
- [x] Document the convention in `docs/compose-extras.md`

**Acceptance**: a project with an extra service (e.g. second cantaloupe) can add it without modifying the toolkit.

### 4.4 — Document the dev workflow
- [x] `docs/local-dev.md` — step-by-step "from zero to running" including the `uv sync` dep flow
- [x] Compare to old workflow so users see the time savings
- [x] Troubleshooting section for common issues (permissions, ports, volume cache)

**Acceptance**: a dev who has never seen the toolkit can go from `git clone` to running Arches in under 10 minutes following only `docs/local-dev.md`.

---

## Stage 5 — CLI (minimum viable)

### 5.1 — `cli/` package skeleton
- [x] `pyproject.toml` using `uv` / setuptools, entry point `arches-toolkit` (uses `hatchling`)
- [x] Framework: `typer` (cleaner than argparse for this size)
- [x] Basic `--version` and `--help`
- [ ] Published to PyPI under `arches-toolkit` (reserve name early)

**Acceptance**: `uvx arches-toolkit --version` works from a clean machine.

### 5.2 — `arches-toolkit add-app <package>`
- [x] Appends entry to `apps.yaml`
- [x] Supports `--source pypi|git`, `--ref`, `--mode release|develop`
- [x] Idempotent (no-op if already present)
- [x] Prints next steps: `uv sync`, INSTALLED_APPS line, URL include

**Acceptance**: running the command twice produces no duplicate entries; running it against a fresh project produces a valid `apps.yaml`.

### 5.3 — `arches-toolkit sync-apps`
- [x] Reads `apps.yaml`
- [x] For release entries: appends to `pyproject.toml` `[project.dependencies]`
- [~] For develop entries: writes `compose.apps.yaml` with bind mounts + editable installs — superseded: develop entries now render as `pkg @ git+repo@ref` deps; `install` overlays an editable install when a local `/workspace` clone exists; `sync-apps` removes any legacy `compose.apps.yaml`
- [x] Idempotent

**Acceptance**: after `add-app` + `sync-apps` + `uv sync`, the app is importable in the web container.

### 5.4 — `arches-toolkit dev`
- [x] Wrapper that runs `docker compose -f compose.yaml -f compose.dev.yaml [-f compose.extras.yaml] up --watch`
- [x] Only includes files that exist
- [x] Passes through unknown flags to `docker compose`

**Acceptance**: `arches-toolkit dev` starts the stack with watch mode; `arches-toolkit dev --build` rebuilds.

### 5.5 — `arches-toolkit patch list` / `patch renew`
- [x] `patch list` — prints table of patch files with header metadata (Upstream, Last-reviewed, days since review)
- [x] `patch renew <name>` — updates `Last-reviewed:` in the specified patch header
- [x] `patch status` — queries GitHub API for upstream PR state of each patch (requires `GH_TOKEN`)

**Acceptance**: commands produce correct output against the patch set from Stage 1.

---

## Stage 6 — First patch: `frontend_configuration` env var

Concrete proof-of-concept for the patch workflow. Solves the non-root-write problem.

### 6.1 — Write the patch
- [x] Modify `arches/apps.py` to read `ARCHES_FRONTEND_CONFIGURATION_DIR` env var
- [x] Default to current path for backward compat
- [x] Commit message includes rationale and before/after

**Acceptance**: patch applies cleanly to `stable/8.1.0` via `git am`; Arches starts with and without the env var.

### 6.2 — Add to `docker/base/patches/`
- [x] Export via `git format-patch`
- [x] Fill in header: `Upstream:`, `Last-reviewed:`, `Reason:` — `Upstream: none yet` (PR not opened)

**Acceptance**: `arches-toolkit patch list` shows the new patch correctly.

### 6.3 — Submit upstream PR
- [ ] Open PR against `archesproject/arches`
- [ ] Update patch header with PR URL

**Acceptance**: PR exists; patch header links to it.

### 6.4 — Wire env var through compose + base Dockerfile
- [x] `docker/project/compose.yaml` sets `ARCHES_FRONTEND_CONFIGURATION_DIR=/var/arches/frontend_configuration` (now in `cli/src/arches_toolkit/_data/compose.yaml`)
- [x] `init` service generates into that path
- [x] Web/worker mount the volume read-only

**Acceptance**: container runs as non-root in dev; k8s pod can run with `readOnlyRootFilesystem: true` (verified later, Phase 2).

---

## Stage 7 — Pilot project migration

### 7.1 — Choose pilot
- [~] Pick a small, actively-developed Arches project (not quartz) — `arches-quartz` used as the working pilot for now
- [ ] Confirm owner has time to work through breakage with us

**Acceptance**: named pilot project with committed owner.

### 7.2 — Migrate
- [x] Create a branch in the pilot repo
- [x] Replace its Dockerfile(s) with the new thin overlay
- [x] Replace `install_app.py` usage with `apps.yaml` + CLI
- [x] Adopt `compose.yaml` + `compose.dev.yaml` from toolkit
- [ ] Remove Makefile (or reduce to a justfile with 3-4 shortcuts)

**Acceptance**: pilot project runs locally via `arches-toolkit dev`; all existing functionality preserved.

### 7.3 — Document migration steps
- [x] `docs/migrating-a-project.md` — step-by-step using the pilot as worked example (lives at [docs/migrating-quartz.md](docs/migrating-quartz.md) + [docs/incremental-migration.md](docs/incremental-migration.md))

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

## Open issue: cold-start signposting

**Status:** resolved 2026-06-11 — `dev` now runs detached (`up -d
--progress quiet`), polls service state, and prints exactly the milestone
line this issue asked for (infra ✓ / init ✓ / webpack ✓ / web ✓ with
elapsed times, a waiting note every 30s, and failure short-circuits
pointing at the right `logs` command). Original sketch kept below for
context.

First `arches-toolkit dev` from a clean state is 60-120s of opaque waiting.
Services come up in dependency order (db → es/rabbitmq → init → webpack →
web/api), and `depends_on: service_healthy` gates mean a user staring at
`docker compose up` output sees a long pause where nothing seems to happen
even though everything is progressing correctly.

The issue isn't speed — the structural floor is roughly: JVM boot for ES
(~15s) + initdb on first Postgres start (~5s) + Django `app.ready()` in
init (~10s) + webpack first compile (~30-60s). None of these parallelise
away cleanly. The issue is that the user doesn't know which step they're
on or how long is left.

Fix: a `arches-toolkit status` (or built into `dev` as a final pre-print)
that polls each service's health and prints a single live-updating line
like:

```
ES: ✓  DB: ✓  RabbitMQ: ✓  init: ✓  webpack: compiling (45s)…  web: waiting on webpack
```

Implementation sketch: `docker compose ps --format json` gives per-service
state and health; webpack's healthcheck output gives "still compiling" vs
"done"; tail those into a single line.

Cost: small. Mostly a wrapper. Doesn't change any infra.

Worth doing because the *first impression* of the toolkit is the cold
start, and right now it looks broken even though it isn't.

---

## Open design problem: ARCHES_SRC bind mount shadows base-image patches

**Status:** model resolved 2026-06-27 — *no fork; upstream + patches is
authoritative everywhere, including the bind mount.* Mechanism designed
below, not yet implemented.

**Resolved model.** There is no F&T fork. The runtime is always upstream
`archesproject/arches` at a ref **+ `git am docker/base/patches/*`**.
Patches are the only divergence and are apply/removable; per-project base
images are built (and pinned) from upstream+patches so a project never
drifts until it rebuilds. The corollary that makes `ARCHES_SRC` first-class
rather than an edge case: a host clone bind-mounted over `/opt/arches`
**must carry the same patch series**, or you live-edit a different arches
than you deploy.

**Decided mechanism — isolated git worktree at the pinned base ref; never
touch the user's working branch.**

The bind mount points at a toolkit-managed *worktree*, not the user's
primary checkout. `ARCHES_SRC` resolves to a worktree of the same repo
(shared `.git`, second checked-out path) created at the project's
`ARCHES_REF` with the patch series applied there. Running the stack has
**zero** effect on the branch the dev actually works on — no commits land
in their history, addressing the "I don't want commits just to run the
container" objection. The worktree being checked out *at the pinned base*
also handles the "apply patches N commits back" case exactly: patches are
applied at the commit they were cut against, not onto a moved-on HEAD.

1. `arches-toolkit arches-src setup [--ref <ARCHES_REF>] [path]` — creates
   the worktree at the pinned ref and applies `docker/base/patches/*`
   there (commits inside the throwaway worktree are invisible to the user's
   branch; `--3way` for drift tolerance). Sets `ARCHES_SRC` to the worktree
   path. Idempotent (already-set-up → no-op / re-sync).
2. `arches-toolkit arches-src remove` — deletes the worktree; the user's
   primary checkout was never modified, so removal is clean (no reverse-
   apply against possibly-edited files).
3. `dev` with `ARCHES_SRC` set runs a consistency check (worktree present,
   at the expected ref, patches applied); if not, it **warns loudly** with
   the one `arches-src setup` command rather than mutating anything. Opt-in
   `--apply-patches` / `.env` flag to auto-setup.
4. Authoring round-trip: the dev edits core *in the worktree* (the live
   source for the container), then `git format-patch` (or an `arches-src
   export-patches` helper) regenerates `docker/base/patches/` — new toolkit
   changes flow straight back into the patch series. Their primary branch
   stays uninvolved.

Why not `git am`/`git apply` onto the user's own checkout: `git am`
pollutes their branch history and breaks on rebase; plain `git apply` to
the working tree intermixes toolkit patches with the dev's own edits in
`git status`, which is exactly what you don't want while live-editing core.
The worktree keeps patch state cleanly separated *and* leaves the working
branch untouched. (`git am` is still used inside the ephemeral base-image
build, where commits are invisible and 3-way robustness is free.)

Tier-1 dependency note: this is part of *finishing the local dev
workflow*, because core-dev via `ARCHES_SRC` is a daily workflow here, not
an edge case. The immediate prerequisite either way is that the patch
series and any lingering fork description agree on the same arches —
today the fork branch (`docker/8.1`, based on `dev/8.1.x` + obsolete
cruft) does **not** match what the base builds (`stable/8.1.2` + the single
curated patch); the resolved model retires the fork, so the patch series
becomes the sole description.

**Rejected mechanisms.** Doc-only (relies on discipline; the daily-use
reality makes silent drift too likely). Patch-overlay `.pth` shim (cleanest
semantics but fiddly, and the bind mount is the simple mental model devs
want). Eliminate-patches-by-upstreaming (the end goal, not a near-term
mechanism).

### Original problem statement (kept for context)

Affects `arches-toolkit dev` with `ARCHES_SRC` set.

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

## Design decision: scaffolded apps need a pushed repo

**Status:** resolved 2026-06-10 — local-only apps are deliberately not
supported; the invariant is **registered ⇒ pushed**.

**The rule.** Everything in `apps.yaml` must be installable by any
teammate. Two constraints make this structural, not a preference:

- `sync-apps` runs `uv lock`, and uv resolves `git+repo@ref` develop deps
  by fetching the ref — an unpushed scaffold fails the lock for the whole
  project. `file://` / path sources lock but bake machine-specific paths
  into the committed `uv.lock`.
- `apps.yaml` and the managed INSTALLED_APPS block in `settings.py` are
  committed; an entry referencing code only one machine has crashes every
  other machine's Django at startup. No install mechanism can fetch code
  that was never pushed — every "local-only" design just moves this crash
  somewhere later and more confusing.

A "venv-only local apps" design (skip pyproject, install editable from
/workspace, warn on sync) was worked through and rejected for exactly that
reason: it trades a loud sync-time error on the author's machine for a
runtime ModuleNotFoundError on a teammate's.

**What `create app` does instead** (to keep the git ceremony minimal):
scaffolds to the **sibling** of the project root by default (where the
`/workspace` mount looks), `git init`s the scaffold with a first commit on
`main`, and prints the two-step path: push to a remote, then
`add-app <pkg> --source git --repo <url> --mode develop` (which accepts the
existing scaffold dir as the working tree, then chains sync + install).
It does **not** auto-register; remote/repo setup is handled independently
by the user.

Guards enforcing the invariant: `sync-apps` rejects develop entries with
no `repo` and git-source release entries with no `repo` (both would
otherwise emit `git+None` deps); `add-app` requires `--repo` for git
sources and pypi-develop.

**Parked alternative** if the one-command push ever becomes real friction:
keep local-only apps truly local — a gitignored `apps.local.yaml` overlay
plus INSTALLED_APPS additions in an uncommitted settings file, so committed
files never reference them. More machinery (two manifests through
sync/install/list, template changes); not worth it today.

---

## Design: app-owned npm dependencies

**Status:** implemented 2026-06-12 (028debb). Schema: `npm: true` on the
apps.yaml entry (must live in the manifest — the committed package.json
has to derive from apps.yaml alone, identically on every machine, and npm
hard-fails on git deps whose repo lacks package.json); add-app auto-sets
it when the develop clone has a root package.json, `--npm/--no-npm`
overrides. sync-apps maintains the managed git entries
(`archesToolkit.managedDependencies` tracking key); install runs the
committed npm reconcile + `--no-save` clone overlay in the webpack
container and freshens the install stamp so the startup hook can't prune
the overlay; `create app` scaffolds a minimal script-light root
package.json. pypi release entries derive `v<version>` tags from exact
pins only — range specifiers are skipped with a warning (set `ref:` or
pin). Remaining from the design, not yet done: app-CI declared-vs-imported
dep check; surfacing npm overlay state in `list`.

**Problem.** Arches has one webpack build per project; app frontend
sources are compiled into it (via the frontend_configuration paths), but
their `import`s resolve against the project's `node_modules`. pip never
populates `node_modules`, so today an app's npm deps must be hand-copied
into the project's `package.json` (upstream's documented answer) — the
old-toolkit pain. Worse, apps actively must NOT install their own deps:
Node resolution walks up from the importing file, so a sibling clone with
its own `node_modules` shadows the project's copies and can bundle a
second `vue` (silently breaks reactivity/provide-inject). One bundle ⇒
one resolution pass: deps are *declared* per app, *installed* at the root.

**Precedent.** Arches core already solves this for itself: the project's
`package.json` has `"arches": "archesproject/arches#stable/8.1.x"` — npm
fetches the git ref and installs core's frontend deps *transitively*. The
pip install and the npm install are parallel views of the same source.

**To be clear about what's load-bearing:** Arches has *no* mechanism for
app npm deps (hence upstream's hand-copy docs). The transitive install is
plain npm behaviour — any dep's deps install transitively — and the whole
design is making the app *be* an npm dep of the project, extending the
core pattern. The toolkit's only role is maintaining that one line per
app. Nothing app-side is toolkit-specific: an app declares deps in a
standard root `package.json`, so **non-toolkit consumers degrade
gracefully** — they add the same one-line git dep by hand (vanilla npm,
documented in the app README; tracks dep changes across app bumps), or
fall back to today's hand-copy, which the declared file makes easier, not
harder. Worth proposing the convention to upstream's app-developer docs.

**Design (A′ + local overlay)** — two layers, mirroring exactly how Python
deps work for develop apps (committed artifacts reference pushed refs;
local clone overlaid after):

1. **Committed layer — push to share.** `sync-apps` manages one npm entry
   per app in the project's `package.json`:
   `"arches-foo": "github:org/arches-foo#<ref>"` — ref derived as on the
   Python side (git source → `ref`; pypi source → `v<version>` tag by
   convention). npm reads the app's own `package.json` at that ref and
   owns transitive resolution/dedup/conflict-nesting — the toolkit never
   parses or merges dep lists. The app's JS landing in
   `node_modules/arches-foo` is dead weight (webpack compiles from
   site-packages or the clone); its *dependencies* at the root are the
   point. Teammates, CI, and the Dockerfile `npm ci` stage all resolve
   from refs; committed package.json + lockfile stay machine-independent.
   JSON has no comments, so managed entries are tracked under an
   npm-ignored root key (e.g. `"archesToolkit": {"managedDependencies":
   [...]}`), mirroring `[tool.arches-toolkit] managed_apps`.
2. **Local overlay — iterate without pushing.** For each develop app with
   a sibling clone, the dev loop reads `/workspace/<dir>/package.json` and
   `npm install --no-save`s its declared deps into the root
   `node_modules` — committed files untouched, live on next webpack
   restart. npm analogue of `uv pip install -e /workspace/<dir>`. Natural
   home: the webpack service startup script (which already has the
   stamp-based reinstall hook) and/or `arches-toolkit install`. Same drift
   contract as the venv: overlay diverges from the lockfile until pushed,
   and a volume rebuild reverts to committed state until re-applied.

Net contract: **push a dep to share it, not to use it** — teammates get a
new npm dep at the same moment they get the code that imports it.

**Deployment path (cloud/prod): unaffected by construction.** Image builds
consume only the committed layer — `npm ci` from package.json + lock,
`uv sync --frozen` from uv.lock — and both lockfiles pin git refs to
concrete SHAs, so builds are reproducible with no mounts or overlays. The
deployed environment is just another teammate: unpushed overlay deps fail
the image build loudly at webpack compile (the right place), and the only
new prod-path requirement is git auth for npm/uv ref fetches in CI (see
known costs). Process convention: `switch-mode <app> release` (pinned
versions) before promoting to production; develop-mode deploys are
SHA-locked branch tips, fine for staging.

The overlay must re-apply *after* the webpack service's stamp-based
`npm install` in the same startup script — a plain install reconciles
node_modules against committed files and can prune overlay deps. (This
ordering constraint holds regardless of the --no-save choice below.)

**Prerequisites.**
- Apps declare frontend deps in a root `package.json`; the `create app`
  scaffold should ship a minimal one (today it ships none). Keep it
  script-light: npm runs `prepare` scripts when installing git deps, so
  either declare no lifecycle scripts or guarantee they run on a bare
  `npm install`.
- pypi-released apps need git tags matching released versions (`v<x.y.z>`)
  for the ref derivation. State as a convention for F&T apps.
- F&T app CI should sanity-check that the declared deps match what the
  frontend code imports — a drifted package.json fails consumers the old
  way. (The standalone app harness idea in the HE backlog would catch
  this naturally.)

**Known costs.**
- npm fetches git refs, so private app repos need git auth wherever npm
  runs (webpack container, Dockerfile frontend stage). Same class of
  problem as `uv lock` fetching `git+repo@ref`, but npm's auth story is
  clunkier.
- Version-conflict policy: start with warn-and-let-npm-nest (nesting is
  fine for non-singleton packages) + a hard error list for singletons
  (`vue`, `pinia`, …) where nesting means a broken bundle.

**Fallback if npm git auth bites** ("A"): sync-apps reads each app's
`package.json` itself (sibling clone, or shipped in the wheel as package
data) and merges the union into the project's `dependencies` under managed
tracking, with semver-intersection conflict detection. Registry-only
project package.json — no npm auth needed — at the cost of the toolkit
doing the merge and needing the file available for release-mode apps.

**Rejected:** npm `file:`/workspace links to `/workspace/<app>` as the
*committed* mechanism — container-only paths break the Dockerfile stage
and host runs, release apps have no clone, and the lockfile would encode
mount-layout paths. (The /workspace mount became writable 2026-06-11 —
setuptools editable installs need to write egg-info into the source tree
— so the earlier read-only objection no longer applies, but the rejection
stands on the other grounds.) Per-app prebuilt bundles (full isolation)
need upstream Arches changes — raise there, don't build here.

**Rejected: overlay with `--save` instead of `--no-save`** (flatten the
app's deps into the project's committed package.json, user uninstalls
unwanted ones). The overlay deps are *derived* state — read mechanically
from the app's package.json; persisting derived state into a committed
file leaves residue: after the app push the flattened copies are redundant
with the git-ref entry's transitive resolution; shared deps across apps
make manual uninstall unsafe (A drops `leaflet`, B still needs it); and
the project file becomes an untracked mix of project-own and app-flattened
deps — the old hand-copy model with a manual remove side. Python symmetry:
`uv pip install -e` doesn't write the app's deps into pyproject either.
The real `--no-save` downside is invisibility — mitigate by logging what
the overlay installed and surfacing npm overlay state in `list`.

---

## Design proposal: native docker compose for running-container commands

**Status:** designed 2026-06-11, not implemented. Sequence after the e2e
smoke test — refactor compose plumbing against a validated baseline.

**Problem.** Every raw `docker compose` command fails in a project today,
because two ingredients exist only inside the wrapper at runtime: the
file list (`-f /site-packages/.../compose.yaml -f …` — nothing in the
project tree) and the interpolation values (`ARCHES_TOOLKIT_DOCKERFILE`,
`ARCHES_SRC` injected into the process env). Consequence: seven bespoke
pass-through wrappers in compose_wrappers.py (`logs`/`ps`/`exec`/
`restart`/`down`/`build`/`manage`), a wrapper surface that grows with
compose's, and no native tooling (IDE integrations, muscle memory).

**Constraint that shapes the answer (do not regress):** the packaged
compose files being the ONLY copy is deliberate — one versioned source of
truth; a toolkit upgrade changes every project's stack immediately;
per-project drift is structurally impossible, not just discouraged.

**Key fact.** Compose v2 splits into two command classes:
- *File-needing*: `up`, `build`, `config` — define what runs. Exactly
  where versioned-config enforcement matters; keep behind the wrapper.
- *Label-based*: `ps`, `logs`, `exec`, `restart`, `down` — resolve
  running containers via the `com.docker.compose.project=<name>` label
  and work with **no compose files at all** (`docker compose -p <name>
  logs web`). For these, only the project *name* is missing, not the
  files.

**Design.**
1. Toolkit-managed `COMPOSE_PROJECT_NAME=<name>` line in `.env`
   (machine-independent, no paths, nothing generated). Raw
   `docker compose ps/logs/exec/restart/down` then work natively from
   the project root. *Verify first:* compose reads `.env` for the project
   name with no config file present (2-minute test); fallback is a
   documented shell export or keeping thin aliases.
2. Collapse the seven wrappers to one generic escape hatch:
   `arches-toolkit compose <args…>` — canonical `-f` stack + env, rest
   passed through verbatim. Any compose subcommand runs against the
   packaged truth. `dev` stays the curated `up --watch` entry point;
   keep `manage` (genuine sugar).
3. Nothing is ever copied into the project tree.

Side benefit: an explicit managed `COMPOSE_PROJECT_NAME` is the first
concrete step toward the multi-project registry idea below — today the
name is inferred from the directory, which is exactly how compose-name
collisions happen.

**Rejected: materialize the stack into the project** (gitignored
`.arches-toolkit/` copies + `COMPOSE_FILE` relative paths in `.env`,
making ALL raw compose commands work, incl. `up`). Buys IDE integration
and inspectability, but reintroduces the drift the package-only model
exists to prevent: stale copies after a toolkit upgrade if the user only
runs raw compose, and hand-edits surviving in a gitignored dir. Stamps
and do-not-edit headers mitigate; package-only makes drift impossible.
One source of truth wins — especially for `up`/`build`, where running
last-version YAML causes real bugs.

**Rejected: compose `include:`** in a small committed compose.yaml —
`include` has no override-merge; the `compose.yaml` + `compose.dev.yaml`
model depends on `-f` overlay semantics, which include rejects on
conflict.

---

## Design proposal: per-project recipe pinning + version-keyed recipe selection

**Status:** designed 2026-06-27, not implemented. Consolidates and
supersedes two scattered backlog bullets — "Per-version overlay strategy"
and the recipe-axis half of "Explicit multi-project registry" — into one
spec. Sequence alongside the native-compose refactor; both touch the same
`.env`/recipe plumbing.

**The gap.** The toolkit ships the build recipe (Dockerfile + compose
files) inside the wheel, so a project never carries them — this kills
stale-Dockerfile drift, the old toolkit's worst pain. But it created an
asymmetry across the two version axes a project actually has:

- *Axis 1 — arches version + patches (the base image).* Pinned per project
  and user-choosable today: `init` writes `ARCHES_TOOLKIT_IMAGE` /
  `ARCHES_TOOLKIT_TAG` to `.env` and compose reads them as the `FROM`. A
  project can already point at a different arches version, or at a
  locally-rebuilt patched base (`docker/base/build.sh --arches-ref
  <branch> --tag my-patched-8.1`, then set the tag in `.env`). Per-project,
  committed, explicit. **No gap here** beyond ergonomics (no
  `image set`/`upgrade` front door — it's a manual `.env` edit).
- *Axis 2 — the build recipe itself (Dockerfile/compose).* NOT pinned per
  project. "Which Dockerfile you get" = "which CLI version is installed on
  the machine," because the recipe lives in the wheel. No project-level
  pin, no compatibility check, no `upgrade`. Upgrading the recipe is a
  global `uv tool upgrade arches-toolkit` that silently moves *every*
  project on the machine at once.

**Why this matters (the requirement).** We routinely run multiple projects
built against varying arches versions on one machine, and sometimes must
patch core, rebuild the base image, and tell a single project to use it.
The old submodule gave us two freedoms the current model removed:
per-project recipe *version*, and per-project recipe *divergence*. We need
those back **without** reintroducing N rotting copies. Axis 1 already
covers "different base image per project"; the missing piece is the recipe
axis. The single generic Dockerfile absorbs version differences only as
long as they're expressible via a different `FROM` tag — it breaks the
moment two supported arches lines need genuinely different recipe logic
(webpack invocation, entrypoint step, 7.x-vs-8.x build differences).

**Design.**

1. **Per-project recipe pin (the keystone).** Record the toolkit/recipe
   version the project targets in committed config (e.g. `[tool.arches-toolkit]
   version = "x.y"`, or an `.env` line). `dev`/`build` check the installed
   CLI satisfies it and warn/error on mismatch. This restores per-project
   recipe *version* + reproducibility (same git commit → same recipe,
   regardless of which CLI the machine happens to have) without copying
   files into the tree. It is what makes everything below safe.

2. **Version-keyed recipe cascade (most-specific-wins).** Store recipes
   keyed by version and resolve them from the version the project already
   declares — do **not** add an independent "pick a Dockerfile" knob (it
   would desync from the base tag):

   ```
   Dockerfile.7.6
   Dockerfile.8        ← every 8.x project rides this
   Dockerfile.8.2      ← added only when 8.2 actually breaks something
   ```

   Resolution: parse the project version → exact minor (`8.2`) → major line
   (`8`) → error. File count stays minimal: we keep `8` until a point
   release forces a fork, then `8.2` is picked up *only* by 8.2 projects;
   everyone else is untouched. Mirrors the existing `templates/{8.1,7.6}/`
   convention. Caveat: compose files merge (layer `compose.arches-8.2.yaml`
   via `-f`, override only deltas), Dockerfiles do **not** — so
   `Dockerfile.8.2` is a whole copy. We accept the occasional whole-file
   fork over `if version >= 8` conditional scatter, *because* the cascade
   keeps forks rare. Selection derives from `ARCHES_TOOLKIT_TAG`; the
   recipe and the `FROM` tag come from one source of truth, so they can't
   desync.

3. **Two distinct upgrades — keep them separate.**
   - `uv tool upgrade arches-toolkit` upgrades the *binary + bundled recipe
     catalog* on the machine. It changes what recipes are **available**; it
     must **not** change what any project **uses**. Safe precisely because
     of (1) + (2): a newer CLI still ships `7.6`/`8`, so old projects
     resolve unchanged.
   - `arches-toolkit upgrade` (new, per-project) bumps *this* project's pin
     (and/or base tag) to a newer available version, landing as a reviewable
     commit in that repo. This is "pull the latest Dockerfile for this
     project" — it decomposes into refresh-the-catalog (`uv tool upgrade`)
     then adopt-it-here (`arches-toolkit upgrade`). An `image set <tag>`
     gives the same explicit front door for the base-image axis.

4. **Distribution: bundle by default.** Recipes are kilobytes of text, so
   the size argument for "pull only what we need" is moot — bundling all
   version-keyed recipes in the wheel is simplest, offline, and atomic with
   the CLI version (`arches-toolkit x.y` *is* a known recipe set). The only
   real cost is release coupling: shipping a fixed `8.2` recipe needs a CLI
   release. For the rare case where that coupling bites (urgent fix, or a
   patched-core project needing a bespoke recipe), add a **digest-pinned
   external recipe override** — a project may point at a local path or a
   pulled, content-addressed recipe ref. This is the submodule's
   per-project divergence freedom, reborn as a rare, digest-locked opt-in
   instead of the default. A full remote *pull* mechanism (decoupling
   recipe cadence from CLI releases entirely) is strictly more machinery
   (fetch, cache, git auth) and is **not** the default — reserve it for if
   release coupling proves painful.

**Net contract.** Pin the recipe per project the way `.env` already pins
the base image; resolve the recipe deterministically from the declared
version via a minimal most-specific cascade; ship recipes bundled with a
rare digest-pinned override for divergence; and keep "upgrade the machine's
catalog" strictly separate from "adopt a new recipe in this project."
Restores both submodule freedoms (per-project recipe version + divergence)
with zero rotting copies.

**Rejected: an independent "which Dockerfile" env.** A second knob separate
from `ARCHES_TOOLKIT_TAG` lets the recipe and base image desync (8.x recipe
on a 7.6 base). Derive the recipe from the one declared version instead.

**Rejected: free per-project Dockerfile copies (the old submodule).**
Brings back N copies that rot; a security/build fix must be hand-propagated
to every repo. The cascade + bundle + digest-override recovers the
freedoms without the copies.

---

## Design proposal: project service topology + run mode

**Status:** designed 2026-06-27, not implemented. Overlaps the
native-compose and recipe-pinning proposals above — same `.env`-managed,
package-only, version-aware machinery. Sequence after the native-compose
refactor (this builds on `COMPOSE_PROJECT_NAME` / `arches-toolkit compose`).

**The asks.** (1) Run a project *without* some bundled services
(cantaloupe today). (2) *Swap* a service for an external/different one
(Elasticsearch is expected to be removed or replaced upstream). (3) Switch
a project into *production mode locally* to debug it as it will actually
run.

**Today: none of these are first-class.** No compose `profiles:` anywhere,
so every `up` brings the whole stack. `dev` hardcodes `compose.yaml +
compose.dev.yaml`, expects all four readiness milestones (infra → init →
webpack → web), and the arches services carry hard `depends_on:
{condition: service_healthy}` edges to db/es/rabbitmq. `settings.py` reads
`ESHOST` / `RABBITMQ_URL` / `CANTALOUPE_HTTP_ENDPOINT` from env (so
*pointing* at an external service already works), but nothing stops the
bundled container from also running, and the depends_on gate still waits
on the local copy. `compose.extras.yaml` only *adds* services.

**Design.**

1. **Optional services via compose profiles + a managed `COMPOSE_PROFILES`
   line in `.env`.** Tag optional services with `profiles:`; a project
   declares what it runs in one toolkit-managed `.env` line (same pattern
   as the proposed `COMPOSE_PROJECT_NAME` — no files copied into the tree).
   - *Cantaloupe is the clean first toggle* — genuinely optional (IIIF
     image server), nothing else hard-depends on it. `profiles: [iiif]`
     (or `[cantaloupe]`), off by default or on by default per project.
   - A toggle command (`arches-toolkit service enable/disable <name>`, or
     folding into a project-config edit) maintains the `COMPOSE_PROFILES`
     line.

2. **Swappable backends, not just optional services — built for ES going
   away.** Treat the search backend (and by extension the broker/IIIF
   endpoints) as a *slot*, not a fixed service. A project either runs the
   bundled service (profile on) or points `ESHOST`/etc. at an external one
   (profile off + env). Two structural requirements this forces:
   - **`depends_on` must be profile-aware.** Compose only starts a service
     in an active profile; a hard `depends_on` on a profiled-out service
     errors. The arches services' dependency edges to es/rabbitmq must be
     gated the same way (or moved to a healthcheck-on-connect model) so a
     project that runs ES externally — or not at all — still boots.
   - **Search backend is version-conditional ⇒ this belongs with the
     version-keyed recipe selection above.** When upstream Arches drops or
     replaces Elasticsearch, that's a different *topology*, not just a flag:
     a different compose overlay (no `elasticsearch` service, different
     init `es setup_indexes` step) selected by the project's arches
     version. This is exactly the "version-conditional behaviour" the
     recipe-pinning note said to design for before it scatters — the ES
     removal is the concrete forcing case. Express it as a version-scoped
     compose overlay (`compose.arches-<ver>.yaml`) resolved from the
     declared version, *not* an `if version` branch in the base compose.

3. **Run-mode selector for prod-debug.** `arches-toolkit dev --mode prod`
   (or a sibling `up --prod`) selects overlays: dev =
   `compose.yaml + compose.dev.yaml`; prod = `compose.yaml` alone (gunicorn,
   prod Dockerfile target, no bind mount / webpack / debugpy), with a
   readiness poll that drops the webpack milestone. Beyond debugging, this
   is the local exercise of the `prod`/`nginx` targets that the Phase 2
   Helm rework needs validated anyway.

**Caveats / non-goals.**
- ES and RabbitMQ are not trivially "off" *today* — search and the celery
  broker depend on them. Profile-gating them means "run external instead of
  local," not "run nothing," until the upstream ES removal lands a topology
  that genuinely doesn't need a search container.
- Keep the package-only invariant: profiles and mode are selected by
  toolkit-managed `.env` config + version resolution, never by copying
  compose files into the project.

**Ties to other proposals.** `COMPOSE_PROFILES` sits beside
`COMPOSE_PROJECT_NAME` (native-compose); version-scoped service overlays
are the same resolver as the Dockerfile/compose cascade (recipe-pinning);
`arches-toolkit compose <args>` is the manual `stop <svc>`/`start <svc>`
escape hatch under the declarative profile config.

**Rejected: per-service on/off by passing service names to `dev`.** Fights
the readiness poll and the depends_on gates, and encodes the choice in a
shell invocation instead of committed project config. Profiles make "what
this project runs" declarative and shareable.

---

## Smoke test outcome (2026-06-11, arches dev/8.2.x)

Full lifecycle exercised on a fresh project against an 8.2 base image:
init → dev (cold start) → add-app (release) → migrate → switch-mode
develop → live-edit via /workspace → switch back to release. Twelve
fixes landed from findings (init image-flag/entrypoint/version-pin
hardening, whitespace-tolerant webpack healthcheck, watch-rebuild
removal, install auto-migrate + warm-start init migrate, writable
/workspace, frontend-config regen + webpack restart on install,
postgis 16 default, switch-mode rollback). One app bug found
(arches-id-generator migration missing a `models` dependency — exactly
what the app-harness backlog idea would catch in app CI).

Follow-ups not yet done:

- ~~**Idempotent init bootstrap.**~~ — resolved 2026-06-27. Dropped the
  dev `init` cold/warm `django_migrations` probe; every step now runs on
  every boot (migrate / createcachetable / es setup_indexes / graph-guarded
  System Settings seed / frontend_configuration regen), so a boot that
  fails partway self-heals on the next instead of stranding the DB in the
  warm path. `es setup_indexes` idempotency confirmed against arches
  `stable/8.1.2` (`SearchEngine.create_index(..., ignore_status=400)`
  swallows the index-exists 400). Dev now matches the always-run prod init
  (minus collectstatic, plus the dev-only regen). Docs in
  `compose-deep-dive.md` updated.
- ~~Cold-start signposting~~ — resolved 2026-06-11 by the detached `dev`
  readiness milestones.

---

## Ideas from HE/arches-containers comparison (backlog)

Surfaced from a comparison of `HistoricEngland/arches-containers` (the `act`
CLI) against this toolkit on 2026-05-28. None are blocking; capture for
later prioritisation.

- **Explicit multi-project registry.** Today the CLI infers the project
  from CWD and lets compose-project-name collisions happen silently. HE
  hash-suffixes container/network names and ships `activate` / `list` /
  `status` / `switch`. A lightweight `~/.config/arches-toolkit/projects.json`
  registry plus `arches-toolkit ls` / `activate` would help devs juggling
  multiple Arches instances (e.g. Catalina + Quartz + vanilla 8.1) on one
  machine without docker-name clashes. The `arches-toolkit list` command
  (landed) is a partial precedent. *(The per-project version/recipe half of
  this is covered by "Design proposal: per-project recipe pinning" above;
  this bullet is now just the name-collision/registry concern.)*
- **`generate-debug-config` for VS Code.** Cheap to produce; removes a
  documentation step; immediately useful with the debugpy port already
  exposed in `compose.dev.yaml`. Output a `.vscode/launch.json` stub.
- **`view` (open browser).** Trivial QoL — open `http://localhost:8000`
  for the active project.
- **`import` / `export` of a project skeleton.** Less compelling for us
  because the project tree is already minimal, but the *idea* of
  round-tripping a project between machines (incl. CI) without losing
  resource-naming identity is worth thinking about for CI parity. Park
  unless a concrete need surfaces.
- **Standalone app harness (`init-app-harness <path>`).** Borrow HE's
  "app-as-project" idea as an *additive* mode on top of `apps.yaml`, not
  a replacement. Scaffolds a minimal sibling project that mounts a single
  app in `develop` mode against stock Arches — nothing else. Use cases:
  (1) contribute to `arches-orm` without cloning Catalina + its `.env` +
  its DB seed; (2) pre-release smoke test that `arches-her` v2.1 still
  works on a clean Arches; (3) triage "is this bug Catalina-specific or
  in the app itself?"; (4) actually exercise the example resource models
  apps ship with. Reuses the existing Dockerfile / compose / CLI — the
  harness is just a tiny one-app `apps.yaml` and an empty Django project.
  Stretch goal: a reusable workflow that runs each F&T-maintained app's
  harness in CI against the latest base image so stock-Arches regressions
  fail loudly at the app level, not when someone tries to consume it.
- **Per-version overlay strategy — design before drift accumulates.**
  *(Folded into "Design proposal: per-project recipe pinning + version-keyed
  recipe selection" above — the version-keyed cascade is the decided
  answer.)* Our single-Dockerfile, single-compose model is cleaner than
  HE's per-version template trees (`_6.1_`, `_6.2_`, `_7.0_` … `_7.6_`), but
  we need a deliberate plan for how version-conditional behaviour will be
  expressed *before* `if version >= 8` branches start scattering through
  compose / Dockerfile / entrypoint. Options: version-scoped compose
  overlays (`compose.arches-7.6.yaml`), build-arg-driven conditionals, or
  per-version patch overlays in the base image. Decide while there's still
  only one supported line.

Things HE does *not* do that we already cover and shouldn't regress on:
no-Dockerfile-in-project-tree, `apps.yaml` + develop mode, `uv sync`
instead of rebuild, patch series with metadata, prod target + Helm chart
in the same repo, scaffolding for widgets/plugins/cards/components.

---

## Phase 2 (deferred — not started in Phase 1)

**Deployment design landed 2026-07-01:** [docs/k8s-deployment.md](docs/k8s-deployment.md)
specifies the dev → staging → production topology (init split into
build-time / release Job / per-pod, storage elimination, tag-based
promotion via the existing Flux pipeline, speed budget, prod-readiness
checklist) and the ordered execution plan. It also enumerates the
image-contract gaps that block everything else: `frontend`-stage script
and output paths vs real arches-admin projects, `webpack-stats.json`
missing from `prod`, `nginx`-target static/media paths, build-time
`frontend_configuration` generation, gunicorn parameterisation, health
endpoint, stdout logging. Sequence: close those gaps → run-mode selector
→ `project-ci.yml` → chart 0.1.0 in `helm-arches`.

- Helm chart rework in the `helm-arches` repo (charts deliberately do NOT
  live in the toolkit — the prototype `chart/` seeded here was removed
  2026-06-11; the WIP toolkit-adaptation diff from 02359ff is exported to
  `helm-arches/toolkit-adaptation-wip.patch` and remains in this repo's
  history). Scope: rebuild against the new image contract using the compose
  files as the spec — init Job (migrate/collectstatic/frontend-config),
  `ARCHES_FRONTEND_CONFIGURATION_DIR` + volumes for the three writable
  paths, non-root + `readOnlyRootFilesystem` security contexts,
  `extraServices` map. Sequence after validating the `prod`/`nginx` image
  targets against a real project.
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
