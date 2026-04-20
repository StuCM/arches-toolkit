# syntax=docker/dockerfile:1.7

ARG ARCHES_TOOLKIT_IMAGE=ghcr.io/flaxandteal/arches-toolkit
ARG ARCHES_TOOLKIT_TAG=latest-arches-stable-8.1.0

FROM node:20-slim AS frontend

WORKDIR /app

COPY package.json package-lock.json* ./

RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    set -eux; \
    if [ -f package-lock.json ]; then \
        npm ci --no-audit --no-fund; \
    else \
        npm install --no-audit --no-fund; \
    fi

COPY . .
RUN npm run build


FROM ${ARCHES_TOOLKIT_IMAGE}:${ARCHES_TOOLKIT_TAG} AS build

USER root
WORKDIR /app

# git is needed by uv for any ``package @ git+...`` dependency.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=app:app pyproject.toml ./
COPY --chown=app:app uv.lock* README.md* ./

RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    set -eux; \
    if [ -f uv.lock ]; then \
        uv sync --frozen --no-install-project --python /venv/bin/python; \
    fi

COPY --chown=app:app . /app

RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    set -eux; \
    uv pip install --python /venv/bin/python -e . ; \
    chown -R app:app /venv


FROM build AS dev

ARG PROJECT_NAME
ARG PROJECT_PACKAGE
ENV PROJECT_NAME=${PROJECT_NAME} \
    PROJECT_PACKAGE=${PROJECT_PACKAGE:-${PROJECT_NAME}}

USER root

RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv pip install --python /venv/bin/python debugpy ipython watchfiles

# Node + git for webpack devserver (arches' package.json pulls git-based deps).
# Only in dev target; prod stays Node-free.
COPY --from=node:20 /usr/local/bin/node /usr/local/bin/node
COPY --from=node:20 /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx && \
    apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# /opt/apps is where sync-apps develop-mode bind mounts land.
# /app ownership was already set by COPY --chown in `build`; no recursive chown.
RUN install -d -o app -g app -m 0775 /opt/apps

USER app:app
WORKDIR /app

EXPOSE 8000 9000 5678

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


# Re-FROM base to shed build-time state; only /venv and /app carry forward.
FROM ${ARCHES_TOOLKIT_IMAGE}:${ARCHES_TOOLKIT_TAG} AS prod

ARG PROJECT_NAME
ARG PROJECT_PACKAGE
ENV PROJECT_NAME=${PROJECT_NAME} \
    PROJECT_PACKAGE=${PROJECT_PACKAGE:-${PROJECT_NAME}}

USER root

COPY --from=build --chown=app:app /venv /venv
COPY --from=build --chown=app:app /app /app
COPY --from=frontend --chown=app:app /app/dist /app/dist

WORKDIR /app
USER app:app
EXPOSE 8000

CMD ["sh", "-c", "exec gunicorn ${PROJECT_PACKAGE}.wsgi:application --bind 0.0.0.0:8000 --workers 3"]


FROM nginx:1.27-alpine AS nginx

COPY --from=frontend /app/dist /usr/share/nginx/html/static

RUN set -eux; mkdir -p /etc/nginx/conf.d; \
    cat > /etc/nginx/conf.d/default.conf <<'NGINX_CONF'
upstream arches_web { server web:8000; }

server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 100M;

    location /static/ {
        alias /var/arches/static_root/;
        access_log off;
        expires 7d;
    }

    location /media/ {
        alias /usr/share/nginx/html/static/;
        access_log off;
        expires 7d;
    }

    location / {
        proxy_pass http://arches_web;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
NGINX_CONF

EXPOSE 80
