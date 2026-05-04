# Upgrade Notes for Arches Toolkit / Stack

Tracks deprecations, version drift, and known patches that should be cleaned up
when bringing the project up to date with the latest arches-toolkit.

## RabbitMQ deprecated features

`docker/rabbitmq.conf` permits two deprecated features so the broker keeps
working with the current Celery/Kombu versions:

- `transient_nonexcl_queues`
- `global_qos`

Both will be removed in a future RabbitMQ major. The fix is upstream in the
client — Celery/Kombu need versions that use per-consumer QoS and avoid
transient non-exclusive queues. Re-check after any Celery upgrade and drop the
permits when the warnings stop firing without them.

## SAML / `django_saml2_auth`

- `WANT_RESPONSE_SIGNED` is `False` because Azure AD only signs the assertion
  envelope by default. If the IdP config is changed to sign the response too,
  flip this back to `True`.
- `ATTRIBUTES_MAP` uses friendly-name claims (`emailAddress`, `name`,
  `displayname`). Confirm these match what Azure is actually sending — full
  schema URIs are the safer default for Azure AD.

## `pyproject.toml` issues

- Line 30: `arches_model_viewer` line has a stray quote — `"arches_model_viewer"
  @ git+...` should be `"arches_model_viewer @ git+..."`. Will block install
  once anyone re-resolves the lockfile.
- `arches_her` is pinned to `dev/2.0.x` (a moving branch). Pin to a tag or
  commit before any stable release.
- `arches_controlled_lists` has no version constraint.

## `certificate_generator` package

Upstream repo (`flaxandteal-arches/certificate-generator`) has two issues that
broke the frontend build and Arches' compatibility check:

1. `pyproject.toml` `[project] name` is `arches-certificate-generator`, but the
   import name is `certificate_generator`. Arches looks up package metadata by
   the AppConfig name, so the names must match. Fix: rename the distribution to
   `certificate_generator`.
2. The `AppConfig` is missing `is_arches_application = True`, so it doesn't
   appear in the generated `webpack-metadata.json` and webpack can't resolve
   its `templates/...` imports. Mirror the pattern used in
   `arches_model_viewer/apps.py`.

Both need PRs upstream. Until then the package can't be cleanly installed
alongside the rest of the stack.
