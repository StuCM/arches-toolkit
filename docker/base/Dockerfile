# syntax=docker/dockerfile:1.7

FROM ubuntu:24.04 AS arches-src

ARG ARCHES_REPO=https://github.com/archesproject/arches.git
ARG ARCHES_REF=stable/8.1.0

ENV DEBIAN_FRONTEND=noninteractive

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Shallow branch/tag clone first; fall back to full clone for SHA refs.
RUN set -eux; \
    if git clone --depth 50 --branch "${ARCHES_REF}" "${ARCHES_REPO}" /src/arches 2>/dev/null; then \
        :; \
    else \
        git clone "${ARCHES_REPO}" /src/arches && cd /src/arches && git checkout "${ARCHES_REF}"; \
    fi

COPY patches/ /patches/

RUN set -eux; cd /src/arches; \
    if ls /patches/*.patch >/dev/null 2>&1; then \
        git -c user.email=ci@local -c user.name=ci am /patches/*.patch; \
    fi

RUN rm -rf /src/arches/.git


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

# -dev headers are here because psycopg2 / python-ldap compile from source on
# install. TODO: stage wheels in arches-src and drop build-essential.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        libgdal-dev \
        libldap2-dev \
        libpq-dev \
        libsasl2-dev \
        passwd \
        python3.12 \
        python3.12-dev \
        python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

# ubuntu:24.04 ships with a default ubuntu:1000 account; remove it so app can
# take uid 1000. Full paths because PATH omits /usr/sbin.
RUN /usr/sbin/userdel --remove ubuntu 2>/dev/null || true && \
    /usr/sbin/groupadd --system --gid 1000 app && \
    /usr/sbin/useradd  --system --uid 1000 --gid 1000 \
             --home-dir /home/app --create-home --shell /bin/bash app

RUN install -d -o app -g app -m 0775 \
        /var/arches \
        /var/arches/frontend_configuration \
        /var/arches/uploadedfiles \
        /var/arches/logs \
        /var/arches/static_root

COPY --from=arches-src --chown=app:app /src/arches /opt/arches

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

CMD ["python", "-c", "import arches; print('arches', arches.__version__)"]
