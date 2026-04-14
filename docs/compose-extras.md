# `compose.extras.yaml` — project-local service additions

## Why

The toolkit's [`compose.yaml`](../docker/project/compose.yaml) and
[`compose.dev.yaml`](../docker/project/compose.dev.yaml) cover the services
every Arches project needs: database, search, queue, image server, and the
three Arches runtimes. Individual projects sometimes need one more thing —
a second cantaloupe for a different tile profile, a local mailpit to catch
outbound email in dev, a minio bucket for S3-compatible testing, a
PostgREST sidecar for a one-off demo.

Editing the toolkit's compose files for every project-specific need would
defeat the point of central ownership. **`compose.extras.yaml` is the
project-local escape hatch.**

## Convention

If a file named `compose.extras.yaml` exists at the project repo root,
`arches-toolkit dev` appends it to the `docker compose` invocation
automatically:

```
docker compose \
  -f docker/project/compose.yaml \
  -f docker/project/compose.dev.yaml \
  -f compose.extras.yaml \          # ← auto-included when present
  up --watch
```

No flag, no opt-in, no registration. Drop the file in; the CLI picks it up.
If the file is absent, the CLI silently skips it.

Projects that want to call `docker compose` manually can add
`-f compose.extras.yaml` themselves — the convention is a CLI convenience,
not a special runtime.

## What to put in it

Anything a plain Compose file can contain. The usual pattern is one or
more additional services plus any named volumes they need. Extras can also
override or extend services from the toolkit compose files — standard
Compose merge semantics apply.

## Minimal worked example — mailpit for outbound email in dev

```yaml
# compose.extras.yaml — project root
services:
  mailpit:
    image: axllent/mailpit:latest
    ports:
      - "1025:1025"   # SMTP
      - "8025:8025"   # web UI
    restart: unless-stopped
```

Then, in your project's `.env` or `settings.py`, point Django at
`mailpit:1025` as its SMTP relay. Browse captured mail at
`http://localhost:8025`. The service appears and disappears with the rest
of the stack, and the rule lives in the project repo — not the toolkit.

## Worked example — second cantaloupe instance

Useful when a project needs separate tile caches for two IIIF image
profiles, or wants to test cantaloupe configuration changes without
disturbing the baseline instance.

```yaml
# compose.extras.yaml
services:
  cantaloupe-thumbs:
    image: uclalibrary/cantaloupe:5.0.3-0
    environment:
      CANTALOUPE_BASE_URI: http://cantaloupe-thumbs:8182
    volumes:
      - cantaloupe_thumbs_cache:/var/cache/cantaloupe
    restart: unless-stopped

volumes:
  cantaloupe_thumbs_cache:
```

Reference `cantaloupe-thumbs:8182` from the project's Django settings
where the secondary tile pipeline is configured.

## What `compose.extras.yaml` is **not** for

- Anything every project needs — that belongs in the toolkit's
  `compose.yaml`. Open an issue or PR against `arches-toolkit`.
- Production configuration — extras are a local-dev ergonomic. Production
  config lives in the Helm chart and values files.
- Secrets — use `.env` (gitignored) or your secret manager of choice.

## See also

- [local-dev.md](local-dev.md) — full dev workflow
- [../docker/project/compose.yaml](../docker/project/compose.yaml)
- [../docker/project/compose.dev.yaml](../docker/project/compose.dev.yaml)
