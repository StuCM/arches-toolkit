"""Single source of truth for cross-cutting toolkit defaults.

CLI commands (init, migrate, …) import from here. The shipped Dockerfile
and compose files duplicate these values as ARG/`${VAR:-…}` fallbacks for
direct `docker build` / `docker compose` invocations without an `.env`;
keep them in sync — there is a CI check (TODO) that compares them.
"""

# Base image users `FROM` and that the CLI runs `arches-admin` inside.
DEFAULT_TOOLKIT_IMAGE = "ghcr.io/flaxandteal/arches-toolkit"

# Floating tag matching the base image's currently-shipped Arches ref.
# Bump together with docker/base/build.sh's --arches-ref default.
DEFAULT_TOOLKIT_TAG = "latest-arches-stable-8.1.2"
