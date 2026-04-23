# Running a local Arches source against your toolkit project

When you need to debug Arches core (add a `console.log`, set a breakpoint, apply
a patch you haven't shipped to the base image yet), the toolkit can bind-mount
a local Arches clone over the base image's `/opt/arches`. Python imports,
webpack bundling, and Django autoreload all follow your clone — no rebuilds
needed between edits.

**How it works:** the base image installs Arches editable from `/opt/arches`
(cloning your chosen ref at base-image build time, plus any patches from
`docker/base/patches/`). The `ARCHES_SRC` overlay bind-mounts your local
Arches repo root over `/opt/arches`, so the editable install now reads from
your clone. Edits to your clone are live — no runtime install, no `.pth`
rewriting.

This page walks through the setup end-to-end.

## Prerequisites

- A working `arches-toolkit dev` on your project (see the top-level
  [README](../README.md)).
- A local Arches clone at a ref that matches your toolkit base image's ref.
  See [Version alignment](#version-alignment) below.
- A base image — either pulled from GHCR (not yet published — see below) or
  built locally via `./docker/base/build.sh`.

## Step 1: clone Arches

```bash
# Pick a location outside the toolkit repo and outside the project repo,
# so there's no accidental coupling.
cd ~/git
git clone https://github.com/archesproject/arches.git
cd arches

# Check out a ref that matches your toolkit base image. If your base image is
# tagged latest-arches-stable-8.1.0, match that:
git checkout stable/8.1.0
```

**Watch the path you record next — it needs to be the repo root**, which
contains `pyproject.toml` and an inner `arches/` package directory. Not the
inner package itself.

```bash
# Verify you have the right level:
ls  # should show: pyproject.toml, README.rst, arches/, releases/, LICENSE.txt, …
#                  NOT: __init__.py, app/, management/ (those are inside the inner arches/)
```

## Step 2: set ARCHES_SRC

Two ways — shell env wins when both are set.

**Option A: in your project's `.env`** (persistent, per-project):

```bash
cd /path/to/your-project
echo "ARCHES_SRC=/home/you/git/arches" >> .env
```

**Option B: shell export** (session-scoped, or per-command):

```bash
export ARCHES_SRC=/home/you/git/arches
# or one-off:
ARCHES_SRC=/home/you/git/arches arches-toolkit dev
```

Verify the CLI is picking it up:

```bash
arches-toolkit dev --dry-run
```

Look for two lines in the output:

```
+ ARCHES_SRC=/home/you/git/arches  (overlay: compose.arches-src.yaml)
+ docker compose … -f …/compose.arches-src.yaml …
```

If either is missing, `ARCHES_SRC` isn't being seen. Common cause: adding to
`.env` in a shell that already has the env var set to something else (shell
wins), or a typo in the variable name.

## Step 3: recreate containers

A named-volume bind mount requires **container recreation** — a `restart` alone
doesn't pick it up.

```bash
arches-toolkit down      # stop containers, keep volumes (db, venv, etc.)
arches-toolkit dev       # come back up with the overlay active
```

## Step 4: verify the overlay

```bash
# /opt/arches should show your clone's contents (repo root — pyproject.toml,
# inner arches/ package directory, etc.)
arches-toolkit exec web ls /opt/arches

# Python imports the editable install, which points at /opt/arches:
arches-toolkit exec web python -c "import arches; print(arches.__file__)"
# expected: /opt/arches/arches/__init__.py
# If you see /venv/lib/.../site-packages/arches/__init__.py, the editable
# install has been clobbered — see troubleshooting.

# webpack sees the same source via the same path (webpack's ROOT_DIR reads
# from /opt/arches through the editable install pointer):
arches-toolkit exec webpack ls /opt/arches
```

## Step 5: edit and observe

- **Python changes** (views, models, management commands): Django autoreload
  picks them up. Watch `arches-toolkit logs web`.
- **JS/Vue changes**: webpack-dev-server rebuilds automatically. Watch
  `arches-toolkit logs webpack` for "Compiled successfully". Hard-refresh the
  browser (Ctrl-Shift-R / Cmd-Shift-R) to bypass cache.

## Version alignment

The toolkit base image pins an Arches ref at build time (default
`stable/8.1.0`). Your clone's checkout must be **reasonably close** to that
ref. Small drift (a few commits) is usually fine; large drift (a different
minor version, or main vs stable) will hit API mismatches, migration
incompatibilities, and missing modules.

Quick alignment check:

```bash
# What ref was the base image built from?
arches-toolkit exec web env | grep ARCHES_REF

# What ref is your local clone on?
cd /path/to/your-clone
git log -1 --oneline
```

If they differ significantly, either:

- Check out your clone to match the base image: `git checkout stable/8.1.0`
- Or rebuild the base image against your clone's ref (see next section).

## Building a custom base image

If you need a base image built against a specific Arches ref or a patched
fork, use the wrapper script:

```bash
cd /path/to/arches-toolkit
./docker/base/build.sh --arches-ref stable/8.1.0
# or, for a non-default repo:
./docker/base/build.sh --arches-repo https://github.com/your-fork/arches.git \
                       --arches-ref my-feature-branch
```

The script builds and `--load`s into your local Docker daemon with two tags:

- `ghcr.io/flaxandteal/arches-toolkit:<toolkit-short-sha>-arches-<sanitised-ref>` (pinned)
- `ghcr.io/flaxandteal/arches-toolkit:latest-arches-<sanitised-ref>` (floating)

Point your project at this image via `.env`:

```bash
ARCHES_TOOLKIT_IMAGE=ghcr.io/flaxandteal/arches-toolkit
ARCHES_TOOLKIT_TAG=latest-arches-stable-8.1.0
```

Then rebuild your project image:

```bash
arches-toolkit down
docker volume rm <project>_venv   # discard the old venv
arches-toolkit dev --build
```

## Troubleshooting

### Edits in the clone don't show up in the container

Volume additions require **container recreation**, not a restart. If you set
`ARCHES_SRC` while the stack was already up, the overlay didn't apply.

```bash
arches-toolkit down
arches-toolkit dev
arches-toolkit exec web ls /opt/arches
# should show your clone's files
```

### `/opt/arches` is empty

The host path is wrong — `$ARCHES_SRC` doesn't exist on your host, so Docker
mounts an empty dir in the container. Verify:

```bash
ls "$ARCHES_SRC"
# should show: pyproject.toml, README.rst, arches/, releases/, LICENSE.txt, …
# This is the Arches *repo root* — the level containing both pyproject.toml
# AND an inner `arches/` Python package directory.
```

If `$ARCHES_SRC` points at the Python package itself (`__init__.py` at its
top level, no `pyproject.toml`), back up one directory — `ARCHES_SRC` must
be the **repo root**, not the inner package.

### ImportError `cannot import name 'VERSION' from 'arches'`

Version skew between your clone and what the ecosystem apps
(`arches-querysets`, `arches-controlled-lists`, etc.) expect. Symptoms:
your clone is on an older ref (e.g. `stable/8.1.0` at a commit before
VERSION was added) but your project's lockfile has, say, `arches-querysets`
at a version that imports `VERSION`.

Fix: check out a ref in your clone that matches what your ecosystem apps
expect. `git pull origin stable/8.1.0` (or check out a tag like `v8.1.2`)
usually resolves it. If the skew is between the BASE IMAGE and the
lockfile (rather than the clone and the lockfile), see
[TASKS.md](../TASKS.md) "Open design problem: pyproject/lockfile version
skew vs base-image arches".

### JS edits don't show up even though Python works

Three common causes:

1. **Browser cache.** Hard-refresh (Ctrl-Shift-R / Cmd-Shift-R).
2. **File not in the webpack bundle.** Arches 8.1 is migrating from
   `arches/app/media/js/` (Knockout, served as static) to `arches/app/src/`
   (Vue3, bundled by webpack). Only changes under `src/` trigger webpack
   rebuilds by default.
3. **webpack watcher didn't propagate through the bind mount.** Rare on
   Linux, more common on macOS. Force-restart webpack:
   `arches-toolkit restart webpack`. Container state keeps the mount, but
   webpack rebuilds the watch tree from scratch.

### Warnings about compose variables (`$STAMP`, `$PROBE`, etc.)

Harmless — some shell variables inside our compose scripts need `$$` escaping
so compose doesn't try to interpolate them. If you see these warnings on a
version of the toolkit that has them fixed, pull the latest.

## Turning it off

Just remove `ARCHES_SRC` from `.env` (or `unset ARCHES_SRC` in your shell),
then `arches-toolkit down && arches-toolkit dev`. Containers come back up
without the overlay; `/opt/arches` reverts to the base image's pre-built
source.

## When to use the overlay

- Tracking down a bug in Arches core — you need `print` / `breakpoint` /
  `console.log`.
- Testing an Arches PR branch against your project.
- Applying a local patch before committing it upstream or to the toolkit's
  patches directory.

## When not to use it

- Everyday project dev. The base image is pinned and reviewable — that's
  the point. Running against a mutable local clone means your local behaviour
  may differ from CI's base-image behaviour.
- When your teammates don't have the same clone. What you see locally won't
  match what they see.
- In CI. CI should always use a pinned base image, never a bind-mounted clone.

## See also

- [docker/base/README.md](../docker/base/README.md) — base image build pipeline
- [compose-deep-dive.md](compose-deep-dive.md) — how the compose overlays compose
- [PLAN.md](../PLAN.md#patches) — why we patch Arches rather than fork
