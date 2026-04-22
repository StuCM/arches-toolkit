# Incremental migration (dev first, CI later)

Migrating a project to the toolkit doesn't have to be a big-bang flip. You can
adopt `arches-toolkit` for local development now and leave your existing CI and
cluster pipelines on the legacy build path, then migrate those later as a
separate exercise.

This page describes that workflow.

## Why incremental?

A full migration replaces three things in a project repo at once:

1. **Local dev tooling** — `arches-toolkit dev` instead of `docker compose up`
   against a project-owned Dockerfile.
2. **CI build artefacts** — the Dockerfile CI uses, any Makefile targets, any
   `.github/workflows/*.yml` that reference them.
3. **Cluster manifests** — if your Helm values or k8s manifests point at a
   specific image registry/tag produced by the old CI.

The three are independent. Dev changes land in developers' laptops; CI changes
land when CI is rebuilt; cluster changes land when the next deploy runs. Doing
them together is possible but couples review and rollback windows that don't
need to be coupled. Dev-first lets your team adopt the toolkit workflow today
while CI and cluster work continues on a separate branch.

## The `--dual-mode` flag

Run migrate with `--dual-mode`:

```bash
arches-toolkit migrate --dual-mode --yes
```

This is equivalent to `--keep-docker --keep-makefile` — both are preserved
verbatim — but names the intent clearly. Everything else `migrate` does is
unchanged:

- `settings.py` gets the env-overrides block appended (idempotent, reads from
  environment, no-op if vars unset — your existing CI env won't trip on this).
- `.env` is written (gitignored — not in your image build context anyway).
- `apps.yaml` is created / merged with detected Arches apps.
- `pyproject.toml` gets the `[tool.arches-toolkit] managed_apps` table plus
  any release-mode deps.
- Stale build artefacts (`node_modules/`, `.venv/`, generated frontend dirs)
  are removed.
- File-ownership sweep command is printed if legacy Docker wrote root-owned
  files into your tree.

What's **not** touched:

- `docker/` stays in place, Dockerfile included.
- `Makefile` stays in place.
- `.github/workflows/`, `.gitlab-ci.yml`, Jenkinsfiles, chart/, k8s manifests —
  migrate doesn't touch any of these in any mode.
- Your image registry / tag / deploy pipeline.

## What changes for developers

After `migrate --dual-mode`, developers can:

```bash
arches-toolkit dev --build            # uses the toolkit-shipped Dockerfile + compose files
```

The toolkit's dev stack uses the base image from GHCR, bind-mounts your source,
populates node_modules and the venv inside container-owned volumes, and runs
webpack with HMR. This is independent of anything in `docker/`.

## What stays the same for CI

Your existing `.github/workflows/build.yml` (or wherever) that runs:

```bash
docker build -f docker/Dockerfile -t myorg/myproject:$SHA .
docker push myorg/myproject:$SHA
```

…continues to work unchanged. CI builds from the legacy Dockerfile, your
cluster still pulls the legacy image tags, deploys proceed as before.

## The coexistence shape

```
project-root/
├── docker/
│   └── Dockerfile          ← CI builds from here (unchanged)
├── Makefile                ← CI may call targets here (unchanged)
├── pyproject.toml          ← used by BOTH paths
├── myapp/
│   └── settings.py         ← env-overrides block appended (safe for both)
├── apps.yaml               ← new, used by toolkit only
├── .env                    ← new, local dev only
└── .dockerignore           ← new, used by toolkit builds only
```

Both paths coexist without stepping on each other. CI ignores `.env` (it's
gitignored and not in its build context anyway). The toolkit ignores
`docker/Dockerfile` — it uses its own shipped Dockerfile, wired via
`ARCHES_TOOLKIT_DOCKERFILE`.

## Phase 2: migrating CI

When you're ready to move CI to the toolkit Dockerfile:

1. Either install `arches-toolkit` in CI and call `arches-toolkit build`, or add
   a slim project-level Dockerfile at the repo root:

   ```dockerfile
   ARG ARCHES_TOOLKIT_TAG=latest-arches-stable-8.1.0
   FROM ghcr.io/flaxandteal/arches-toolkit:${ARCHES_TOOLKIT_TAG} AS prod
   COPY . /app
   RUN uv pip install --python /venv/bin/python -e /app
   CMD ["gunicorn", "myproject.wsgi:application", "--bind", "0.0.0.0:8000"]
   ```

2. Update your CI to use the new Dockerfile (or the `arches-toolkit build` call).
3. Verify that image boots in staging before swapping prod traffic.
4. Once you're on the toolkit in CI too, `rm -rf docker/ Makefile` — the dual
   state is no longer needed.

## Caveat: base image availability

`arches-toolkit dev` pulls `ghcr.io/flaxandteal/arches-toolkit:…`. Until the
Stage 2 CI workflow (`.github/workflows/base-image.yml`) publishes that tag,
adopters need to build the base image locally:

```bash
cd <arches-toolkit checkout>
./docker/base/build.sh
```

Once the base image is on GHCR this step disappears.

## See also

- [migrating-quartz.md](migrating-quartz.md) — worked example (currently does a
  full migration; will be cross-linked once `--dual-mode` is the recommended path
  for existing deployed projects)
- [local-dev.md](local-dev.md) — day-to-day dev workflow using `arches-toolkit dev`
- [create.md](create.md) — scaffolding new apps, widgets, plugins, etc.
