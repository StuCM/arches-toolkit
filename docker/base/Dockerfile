# syntax=docker/dockerfile:1.7
#
# arches-toolkit base image
# -------------------------
# Multi-stage build that produces a slim Ubuntu 24.04 + Python 3.12 image with
# upstream Arches installed into a uv-managed venv at /venv.
#
# Stages:
#   arches-src - clones archesproject/arches at $ARCHES_REF, applies any
#                patches under /patches/*.patch via `git am`. Build tools and
#                git live here only; nothing from this stage ships at runtime
#                except the patched source tree copied into /opt/arches.
#   base       - runtime image: ubuntu:24.04 + runtime libs + uv + venv with
#                Arches pip-installed. Non-root user app:app (1000:1000).
#
# Build args:
#   ARCHES_REPO - upstream git URL (default archesproject/arches)
#   ARCHES_REF  - branch, tag, or full SHA (default stable/8.1.0)
#
# Published as:
#   ghcr.io/flaxandteal/arches-toolkit:<toolkit-sha>-arches-<sanitised-ref>
#   ghcr.io/flaxandteal/arches-toolkit:latest-arches-<sanitised-ref>

# ---------------------------------------------------------------------------
# Stage 1: arches-src - fetch and patch upstream Arches
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS arches-src

ARG ARCHES_REPO=https://github.com/archesproject/arches.git
ARG ARCHES_REF=stable/8.1.0

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Clone with a generous depth so SHAs and tags resolve. Branches still work
# with --branch; SHAs require a full clone fallback.
RUN --mount=type=cache,target=/root/.cache/git,sharing=locked \
    set -eux; \
    if git clone --depth 50 --branch "${ARCHES_REF}" "${ARCHES_REPO}" /src/arches 2>/dev/null; then \
        :; \
    else \
        echo "Shallow branch/tag clone failed; falling back to full clone for SHA support."; \
        git clone "${ARCHES_REPO}" /src/arches; \
        cd /src/arches && git checkout "${ARCHES_REF}"; \
    fi

# Copy the patch series. The directory may be empty (the toolkit explicitly
# carries zero patches at present; see docs/fork-inventory.md).
COPY patches/ /patches/

# Apply patches if and only if at least one *.patch file is present. Glob
# expansion in `ls` returns non-zero on no-match, which we use as the gate.
# git am needs an identity even though we never commit out of this stage.
RUN set -eux; \
    cd /src/arches; \
    if ls /patches/*.patch >/dev/null 2>&1; then \
        echo "Applying $(ls /patches/*.patch | wc -l) patch(es)..."; \
        git -c user.email=ci@arches-toolkit.local \
            -c user.name='arches-toolkit CI' \
            am /patches/*.patch; \
    else \
        echo "No patches to apply (patches/ is empty)."; \
    fi

# Drop the .git dir to keep the runtime stage lean. The src copy below carries
# only the working tree.
RUN rm -rf /src/arches/.git

# ---------------------------------------------------------------------------
# Stage 2: base - runtime image
# ---------------------------------------------------------------------------
FROM ubuntu:24.04 AS base

ARG ARCHES_REF=stable/8.1.0

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/venv \
    PATH=/venv/bin:/usr/local/bin:/usr/bin:/bin \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/bin/python3.12 \
    ARCHES_REF=${ARCHES_REF}

# Runtime system deps. GDAL/PostgreSQL/LDAP/SASL are the well-known
# transitive requirements of Arches' Python stack. We deliberately install
# the -dev variants here too: `uv pip install /opt/arches` builds a couple of
# wheels (notably psycopg2 and any C-extension deps not available as binary
# wheels for python 3.12 on arm64). Without dev headers the install fails or
# silently degrades. This bloats the image by ~40-60MB; future work
# (TODO: cf. PLAN.md "Don't" caveat) is to stage pre-built wheels in
# arches-src and copy them here so we can drop the -dev packages.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgdal-dev \
        libldap2-dev \
        libpq-dev \
        libsasl2-dev \
        python3.12 \
        python3.12-dev \
        python3.12-venv \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv (single static binary). Pinned to a recent release for
# reproducibility; bump deliberately.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# Create the unprivileged runtime user before any chowned mkdirs.
RUN groupadd --system --gid 1000 app && \
    useradd  --system --uid 1000 --gid 1000 \
             --home-dir /home/app --create-home \
             --shell /bin/bash app

# Pre-create writable runtime paths owned by app and declare them as volumes.
# These four paths cover everything Arches expects to write at runtime.
#
# NOTE: /var/arches/frontend_configuration is not yet *fully* runtime-clean.
# Upstream arches/apps.py (as of stable/8.1.0) hardcodes the
# frontend_configuration output path under the code tree. Stage 6 of the
# toolkit plan adds a patch parameterising that path via the env var
# ARCHES_FRONTEND_CONFIGURATION_DIR. Until that patch ships, this volume is
# scaffolding: containers that need to (re)generate frontend configuration
# must currently still write under /opt/arches/arches/app/. See PLAN.md
# "Runtime-writable paths" and TASKS.md Stage 6.
RUN install -d -o app -g app -m 0775 \
        /var/arches \
        /var/arches/frontend_configuration \
        /var/arches/uploadedfiles \
        /var/arches/logs \
        /var/arches/static_root

# Bring the patched Arches source across from the previous stage.
COPY --from=arches-src --chown=app:app /src/arches /opt/arches

# Create the venv as root, then install Arches into it. Cache mount keeps
# uv's wheel cache between builds.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    set -eux; \
    uv venv --python /usr/bin/python3.12 /venv; \
    uv pip install --python /venv/bin/python --upgrade pip setuptools wheel; \
    uv pip install --python /venv/bin/python /opt/arches; \
    chown -R app:app /venv

VOLUME ["/var/arches/frontend_configuration", \
        "/var/arches/uploadedfiles", \
        "/var/arches/logs", \
        "/var/arches/static_root"]

USER app:app
WORKDIR /opt/arches

# Sanity check baked into the image: `docker run <image> python -c "import arches"`.
CMD ["python", "-c", "import arches; print('arches', arches.__version__)"]
