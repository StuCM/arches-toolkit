# arches chart (0.1.0)

Deploys an Arches project built with the arches-toolkit image contract.
Implements [docs/k8s-deployment.md](../../docs/k8s-deployment.md); the
delta from the old chart 0.0.19 is catalogued in
[docs/helm-migration-audit.md](../../docs/helm-migration-audit.md).

> **Location note.** Charts were decided (2026-06-11) to live in
> `helm-arches`, not this repo. This chart is developed here so it can
> iterate against the image contract and compose files in one place;
> promote it to `helm-arches` (or revisit the decision) before the first
> real release. Nothing in it depends on being in this repo.

## What it deploys

| Resource | Component | Notes |
|---|---|---|
| Deployment web (+Service, HPA, PDB) | gunicorn, ≥2 replicas, rolling `maxUnavailable: 0` | |
| Deployment worker | celery with recycling flags | heavy tasks belong in one-off Jobs |
| Deployment api (+Service) | values-gated, **off by default** | |
| Deployment static (+Service) | project `nginx` image target, baked assets | |
| Deployment cantaloupe (+Service) | values-gated, off by default | mounts uploads read-only |
| Job init | Helm pre-install/pre-upgrade hook | migrate / createcachetable / es setup_indexes / seed — idempotent, no collectstatic |
| PVC uploadedfiles | RWX, `helm.sh/resource-policy: keep` | the one real state |
| ConfigMap/Secret `<release>-env` | plain + secret env | prod: point at SOPS-managed existing secrets instead |
| Ingress | `/static/` → static, `/` → web | |

Backing services (Postgres/ES/RabbitMQ) are consumed as endpoints
(`postgres.host`, `elasticsearch.host`, `rabbitmq.*`) — bring managed
services, operators, or uncomment the Bitnami dependencies in
`Chart.yaml` for an in-cluster staging stack.

## Prerequisites

- An image built from the toolkit Dockerfile `prod` target, and one from
  the `nginx` target (default name: `<repository>-static`).
- **Image-contract gaps 1–4** from docs/k8s-deployment.md are not yet
  landed; until they are, set `frontendConfiguration.generateAtBoot: true`
  (the default — per-pod initContainer fallback) and expect the static
  image to need the collectstatic bake before `/static/` serves correctly.
- Secrets: in production supply `postgres.existingSecret`,
  `rabbitmq.existingSecret`, `existingSecretEnv` (with
  `DJANGO_SECRET_KEY`) via the SOPS pipeline. Inline `postgres.password`
  / `rabbitmq.password` / `secretEnv` render into a chart-managed Secret
  — dev/staging convenience only.

## Minimal values

```yaml
project:
  package: myproject
image:
  repository: ghcr.io/flaxandteal/arches-myproject
  tag: main-123            # staging; prod pins vX.Y.Z
postgres:
  host: myproject-postgresql
  existingSecret: myproject-pg
elasticsearch:
  host: myproject-elasticsearch
rabbitmq:
  existingSecret: myproject-mq
existingSecretEnv: myproject-env   # DJANGO_SECRET_KEY etc.
ingress:
  enabled: true
  host: myproject.example.org
```

## Sizing

Defaults are the production starting numbers from docs/k8s-deployment.md
(requests = steady state, memory limits ≈ ≤2× request, no CPU limits).
A dev/staging namespace halves requests and sets
`web.autoscaling.enabled: false`, `web.replicaCount: 1` — same shape,
smaller values.

## Break-glass

`containerSecurityContext.readOnlyRootFilesystem: false` is the
documented emergency toggle (docs/k8s-deployment.md, operational access).
`kubectl exec … python manage.py <cmd>` works without it.

## Validating changes

```sh
helm lint . -f ci/test-values.yaml
helm template test . -f ci/test-values.yaml
```
