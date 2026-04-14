#!/usr/bin/env bash
#
# build.sh - thin wrapper around `docker buildx build` for the arches-toolkit
# base image. Covers local dev (default --load) and CI (--publish to push).
#
# Usage:
#   ./build.sh [--arches-ref <ref>] [--arches-repo <url>]
#              [--platform <list>] [--publish] [--tag <extra-tag>]
#
# Defaults:
#   --arches-ref   stable/8.1.0
#   --arches-repo  https://github.com/archesproject/arches.git
#   --platform     linux/amd64
#   (no --publish: --load instead, single-platform only)
#
# Image names emitted (in addition to any --tag):
#   ghcr.io/flaxandteal/arches-toolkit:<short-toolkit-sha>-arches-<sanitised-ref>
#   ghcr.io/flaxandteal/arches-toolkit:latest-arches-<sanitised-ref>
#
# The "<sanitised-ref>" replaces "/" with "-" so e.g. "stable/8.1.0" becomes
# "stable-8.1.0" (slashes are not legal in OCI tags).

set -euo pipefail

# ---- defaults --------------------------------------------------------------

ARCHES_REF="stable/8.1.0"
ARCHES_REPO="https://github.com/archesproject/arches.git"
PLATFORM="linux/amd64"
PUBLISH=0
EXTRA_TAGS=()

REGISTRY="ghcr.io/flaxandteal/arches-toolkit"

# ---- arg parsing -----------------------------------------------------------

usage() {
    sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --arches-ref)   ARCHES_REF="$2"; shift 2 ;;
        --arches-repo)  ARCHES_REPO="$2"; shift 2 ;;
        --platform)     PLATFORM="$2"; shift 2 ;;
        --publish)      PUBLISH=1; shift ;;
        --tag)          EXTRA_TAGS+=("$2"); shift 2 ;;
        -h|--help)      usage 0 ;;
        *)              echo "unknown arg: $1" >&2; usage 1 ;;
    esac
done

# ---- derived values --------------------------------------------------------

# Locate the base/ directory (where this script lives) and the toolkit repo
# root (two levels up). Resolve symlinks.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." >/dev/null 2>&1 && pwd)"

# Sanitise the ref for use in an OCI tag: slashes -> hyphens. Strip anything
# else that's not [A-Za-z0-9._-].
SANITISED_REF="$(printf '%s' "${ARCHES_REF}" | tr '/' '-' | tr -c 'A-Za-z0-9._-' '-' | sed 's/-\{2,\}/-/g; s/^-//; s/-$//')"

# Toolkit short SHA (best-effort: fall back to "dev" if not a git checkout).
if SHORT_SHA="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null)"; then
    :
else
    SHORT_SHA="dev"
fi

PINNED_TAG="${REGISTRY}:${SHORT_SHA}-arches-${SANITISED_REF}"
FLOATING_TAG="${REGISTRY}:latest-arches-${SANITISED_REF}"

# ---- build command ---------------------------------------------------------

BUILD_ARGS=(
    buildx build
    --file "${SCRIPT_DIR}/Dockerfile"
    --platform "${PLATFORM}"
    --build-arg "ARCHES_REPO=${ARCHES_REPO}"
    --build-arg "ARCHES_REF=${ARCHES_REF}"
    --tag "${PINNED_TAG}"
    --tag "${FLOATING_TAG}"
)

for t in "${EXTRA_TAGS[@]:-}"; do
    [[ -n "${t}" ]] && BUILD_ARGS+=( --tag "${t}" )
done

if [[ "${PUBLISH}" -eq 1 ]]; then
    BUILD_ARGS+=( --push )
else
    # --load only supports a single platform. Warn and downgrade gracefully.
    if [[ "${PLATFORM}" == *,* ]]; then
        echo "warning: --load (the default when --publish is absent) cannot" \
             "load multi-platform images; using --output=type=image (no load)." >&2
        BUILD_ARGS+=( --output=type=image )
    else
        BUILD_ARGS+=( --load )
    fi
fi

# Build context is the base/ directory (so patches/ resolves alongside the
# Dockerfile).
BUILD_ARGS+=( "${SCRIPT_DIR}" )

# ---- go --------------------------------------------------------------------

printf '+ docker'
for a in "${BUILD_ARGS[@]}"; do
    printf ' %q' "${a}"
done
printf '\n'

exec docker "${BUILD_ARGS[@]}"
