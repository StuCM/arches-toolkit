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
- [x] `develop.watch` rules — `sync` for code paths, `rebuild` for `pyproject.toml`
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

**Status:** UX papercut, not a correctness bug.

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

## Design proposal: app-owned npm dependencies

**Status:** designed 2026-06-10, not implemented. Next sizeable feature.

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
  scaffold should ship a minimal one (today it ships none).
- pypi-released apps need git tags matching released versions (`v<x.y.z>`)
  for the ref derivation. State as a convention for F&T apps.

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
and host runs, `/workspace` is read-only (npm nests into the link target
on conflicts), release apps have no clone, and the lockfile would encode
mount-layout paths. Per-app prebuilt bundles (full isolation) need
upstream Arches changes — raise there, don't build here.

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
  (landed) is a partial precedent.
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
- **Per-version overlay strategy — design before drift accumulates.** Our
  single-Dockerfile, single-compose model is cleaner than HE's per-version
  template trees (`_6.1_`, `_6.2_`, `_7.0_` … `_7.6_`), but we need a
  deliberate plan for how version-conditional behaviour will be expressed
  *before* `if version >= 8` branches start scattering through compose /
  Dockerfile / entrypoint. Options: version-scoped compose overlays
  (`compose.arches-7.6.yaml`), build-arg-driven conditionals, or per-version
  patch overlays in the base image. Decide while there's still only one
  supported line.

Things HE does *not* do that we already cover and shouldn't regress on:
no-Dockerfile-in-project-tree, `apps.yaml` + develop mode, `uv sync`
instead of rebuild, patch series with metadata, prod target + Helm chart
in the same repo, scaffolding for widgets/plugins/cards/components.

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
