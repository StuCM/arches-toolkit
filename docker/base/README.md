# Base image

Builds `ghcr.io/flaxandteal/arches-toolkit:…` — the image every project `FROM`s. Upstream Arches + a reviewable patch series, installed editable under a non-root user.

Most devs don't need to touch this directory: the published image on GHCR is pulled by `arches-toolkit dev`. Read on if you want a build against a different Arches ref, a custom fork, or a local image before the CI publish lands.

## Contents

- [`Dockerfile`](Dockerfile) — multi-stage: clone upstream → apply patches → install via `uv`
- [`build.sh`](build.sh) — wrapper around `docker buildx build` for local and CI use
- [`patches/`](patches/) — `*.patch` files applied via `git am` at build time ([patches/README.md](patches/README.md))

## Building locally

```bash
./docker/base/build.sh                              # defaults: stable/8.1.0, linux/amd64, --load
./docker/base/build.sh --arches-ref dev/8.1.x       # different upstream branch
./docker/base/build.sh --arches-ref v8.1.0          # a tag
./docker/base/build.sh --arches-ref abc1234         # a commit SHA
./docker/base/build.sh --arches-repo https://github.com/your-fork/arches.git \
                      --arches-ref my-branch       # a fork
./docker/base/build.sh -h                           # full flag list
```

**`ARCHES_REF` accepts branches, tags, or commit SHAs.** [Dockerfile:20-25](Dockerfile#L20-L25) tries a shallow `git clone --branch` first (covers branches + tags) and falls back to a full clone + `git checkout` for anything else (covers SHAs).

## Tags emitted

Every build produces two tags on `ghcr.io/flaxandteal/arches-toolkit` ([build.sh:72-73](build.sh#L72-L73)):

| Tag | Purpose |
|---|---|
| `<toolkit-short-sha>-arches-<sanitised-ref>` | **Pinned.** Reproducible — identifies the arches ref *and* the toolkit commit that built it. Prefer this for CI / prod. |
| `latest-arches-<sanitised-ref>` | **Floating.** Moves with every rebuild of that ref. Convenient for local dev. |

`<sanitised-ref>` is the arches ref with `/` replaced by `-` (slashes aren't legal in OCI tags):

| `--arches-ref` | Floating tag |
|---|---|
| `stable/8.1.0` | `latest-arches-stable-8.1.0` |
| `dev/8.1.x` | `latest-arches-dev-8.1.x` |
| `v8.1.0` | `latest-arches-v8.1.0` |
| `abc1234` | `latest-arches-abc1234` |

Pass `--tag <extra>` to `build.sh` to add extra tags on top.

## Publishing (CI)

[`.github/workflows/base-image.yml`](../../.github/workflows/base-image.yml) builds and publishes on:

- push to `main` touching `docker/base/**`
- manual `workflow_dispatch` with a custom `arches_ref` input

The default matrix covers `stable/8.1.0` and `dev/8.1.x`. Post-build steps: Trivy vulnerability scan (fails build on HIGH/CRITICAL), SBOM generation via syft. Cosign signing is scaffolded but disabled pending action pinning.

## Consuming the base image

In a project's `.env`:

```bash
ARCHES_TOOLKIT_IMAGE=ghcr.io/flaxandteal/arches-toolkit
ARCHES_TOOLKIT_TAG=latest-arches-stable-8.1.0    # default
```

Both are referenced by the toolkit-shipped `compose.yaml`/`compose.dev.yaml` and the project Dockerfile's `FROM`. Pin to the `<short-sha>-arches-<ref>` form for reproducibility; use `latest-arches-<ref>` to follow a moving ref.

If you built locally and it's not on GHCR, either set `ARCHES_TOOLKIT_IMAGE=arches-toolkit-local-test` (or whatever `--tag` you passed) or rely on the floating tag being in your local Docker daemon — `docker compose build` resolves local tags before pulling.

## Patches

See [patches/README.md](patches/README.md) for the patch format and [../../docs/fork-inventory.md](../../docs/fork-inventory.md) for why the current patch set is what it is.

## See also

- [../../docs/local-arches-src.md](../../docs/local-arches-src.md) — bind-mount a live arches clone instead of rebuilding the base
- [../../PLAN.md](../../PLAN.md) — design rationale
