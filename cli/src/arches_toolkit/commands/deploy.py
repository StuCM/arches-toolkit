"""``arches-toolkit deploy`` — one-command deploy of a project to k8s.

Two modes, selected per environment (docs/k8s-deployment.md, single-command
deploys):

- **direct** (dev / ephemeral namespaces): ``helm upgrade --install`` of the
  packaged charts against the current (or configured) kube context. With
  ``devServices`` on, a minimal in-cluster PostGIS/Elasticsearch/RabbitMQ
  stack is installed first and the app chart is wired to it — so
  ``arches-toolkit deploy dev`` is genuinely one command on an empty
  namespace.
- **gitops** (staging / production): deploying *is* committing to the fluxcd
  repo — Flux applies, the cluster is never touched directly. Not yet
  implemented; the command explains the manual path.

Environments come from an optional ``deploy.yaml`` at the project root;
without one, built-in defaults provide ``dev`` (direct + devServices) and
``staging``/``prod`` (gitops). Charts ship as CLI package data — the same
package-only invariant as the compose files; nothing is copied into the
project tree.
"""

from __future__ import annotations

import copy
import json
import os
import re
import secrets as _secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

import typer
import yaml

from .. import _output
from .._util import package_data_path

APP_CHART = "helm/arches"
DEV_SERVICES_CHART = "helm/arches-dev-services"
DEPLOY_CONFIG = "deploy.yaml"
SECRETS_FILE_TEMPLATE = ".deploy-secrets.{env}.yaml"
SECRETS_GITIGNORE_PATTERN = ".deploy-secrets.*.yaml"

FLUX_OWNERSHIP_LABELS = (
    "kustomize.toolkit.fluxcd.io/name",
    "helm.toolkit.fluxcd.io/name",
)

BUILTIN_ENVIRONMENTS: dict[str, dict] = {
    "dev": {"mode": "direct", "devServices": True, "profile": "dev"},
    "staging": {"mode": "gitops"},
    "prod": {"mode": "gitops"},
}


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Parse the project .env into a dict (same minimal reader as dev.py)."""
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def _load_environments(project_root: Path) -> dict[str, dict]:
    """Built-in environments overlaid with the project's deploy.yaml."""
    envs = copy.deepcopy(BUILTIN_ENVIRONMENTS)
    config_path = project_root / DEPLOY_CONFIG
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        for name, spec in (config.get("environments") or {}).items():
            merged = envs.get(name, {}) | (spec or {})
            envs[name] = merged
    return envs


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _load_or_create_secrets(project_root: Path, env_name: str) -> dict[str, str]:
    """Stable per-project dev secrets, generated once and kept out of git.

    Local-only convenience for direct mode; gitops environments use the
    SOPS pipeline and never touch this file.
    """
    path = project_root / SECRETS_FILE_TEMPLATE.format(env=env_name)
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    generated = {
        "djangoSecretKey": _secrets.token_urlsafe(48),
        "pgPassword": _secrets.token_urlsafe(24),
        "rabbitmqPassword": _secrets.token_urlsafe(24),
    }
    path.write_text(yaml.safe_dump(generated), encoding="utf-8")
    path.chmod(0o600)
    _ensure_gitignored(project_root)
    typer.echo(f"  generated {path.name} (gitignored; stable across deploys)", err=True)
    return generated


def _ensure_gitignored(project_root: Path) -> None:
    gitignore = project_root / ".gitignore"
    if gitignore.exists() and SECRETS_GITIGNORE_PATTERN in gitignore.read_text(encoding="utf-8"):
        return
    with gitignore.open("a", encoding="utf-8") as fh:
        fh.write(f"\n# arches-toolkit deploy: local-only generated secrets\n{SECRETS_GITIGNORE_PATTERN}\n")
    typer.echo(f"  added {SECRETS_GITIGNORE_PATTERN} to .gitignore", err=True)


def _flux_owns_namespace(namespace: str, context: str | None) -> bool:
    """Best-effort check that Flux manages the target namespace.

    Direct helm against a Flux-owned namespace gets reverted or fought by
    the controller — refuse rather than corrupt. No kubectl / no namespace
    → not owned as far as we can tell.
    """
    if shutil.which("kubectl") is None:
        return False
    argv = ["kubectl", "get", "namespace", namespace, "-o", "json"]
    if context:
        argv += ["--context", context]
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        return False
    try:
        labels = (json.loads(result.stdout).get("metadata") or {}).get("labels") or {}
    except ValueError:
        return False
    return any(label in labels for label in FLUX_OWNERSHIP_LABELS)


def _helm_argv(
    release: str,
    chart_dir: Path,
    namespace: str,
    context: str | None,
    values_files: list[Path],
    *,
    render: bool,
) -> list[str]:
    if render:
        argv = ["helm", "template", release, str(chart_dir)]
    else:
        argv = [
            "helm", "upgrade", "--install", release, str(chart_dir),
            "--create-namespace", "--wait", "--timeout", "10m",
        ]
    argv += ["--namespace", namespace]
    if context:
        argv += ["--kube-context", context]
    for f in values_files:
        argv += ["-f", str(f)]
    return argv


def _run(argv: list[str], *, dry_run: bool) -> None:
    _output.cmd(argv)
    if dry_run:
        typer.echo("  " + " ".join(argv))
        return
    completed = subprocess.run(argv)
    if completed.returncode != 0:
        raise typer.Exit(completed.returncode)


# --------------------------------------------------------------------------- #
# GitOps promotion (staging / prod)
# --------------------------------------------------------------------------- #


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        typer.echo(result.stderr.strip(), err=True)
        raise typer.Exit(result.returncode)
    return result.stdout.strip()


def _set_yaml_path(documents: list, dotted_path: str, value: str) -> list[tuple[str, str]]:
    """Set ``dotted_path`` to ``value`` in every document where it resolves.

    Returns (old, new) per updated document. Documents that don't contain
    the path are skipped — fluxcd files are often multi-doc (HelmRelease +
    ImagePolicy + …).
    """
    *parents, leaf = dotted_path.split(".")
    changes: list[tuple[str, str]] = []
    for doc in documents:
        node = doc
        try:
            for key in parents:
                node = node[key]
            old = node[leaf]
        except (KeyError, TypeError):
            continue
        if str(old) != value:
            node[leaf] = value
        changes.append((str(old), value))
    return changes


def _pr_url(repo: str, branch: str) -> str | None:
    """Best-effort GitHub compare URL for a pushed branch."""
    m = re.match(r"(?:git@github\.com:|https://github\.com/)([^/]+/[^/.]+?)(?:\.git)?/?$", repo)
    if m:
        return f"https://github.com/{m.group(1)}/pull/new/{branch}"
    return None


def _gitops_deploy(
    project_name: str,
    environment: str,
    cfg: dict,
    tag: str,
    *,
    dry_run: bool,
) -> None:
    """Deploying to a GitOps environment IS committing to the fluxcd repo.

    Clones the configured repo, bumps the image tag inside the HelmRelease
    values (comment/format-preserving round-trip — these files are
    hand-maintained), and pushes either a `deploy/...` branch for review
    (default) or the base branch directly. Flux applies; this machine never
    touches the cluster.
    """
    from ruamel.yaml import YAML  # local import: only the gitops path needs it

    repo = cfg.get("repo")
    file_rel = cfg.get("file")
    if not repo or not file_rel:
        raise typer.BadParameter(
            f"environment {environment!r} is gitops but deploy.yaml lacks "
            "gitops.repo / gitops.file — see docs/k8s-deployment.md "
            "(single-command deploys) for the schema"
        )
    if not tag:
        raise typer.BadParameter(
            "gitops promotion needs an explicit --tag "
            "(main-<bid> for staging, vX.Y.Z for prod) — the local PROJECT_TAG "
            "is deliberately not used"
        )
    base_branch = cfg.get("branch", "main")
    push_mode = cfg.get("push", "branch")
    if push_mode not in ("branch", "direct"):
        raise typer.BadParameter(f"gitops.push must be 'branch' or 'direct', got {push_mode!r}")
    tag_paths = cfg.get("tagPath", "spec.values.image.tag")
    if isinstance(tag_paths, str):
        tag_paths = [tag_paths]
    deploy_branch = f"deploy/{project_name}-{environment}-{tag}"

    if dry_run:
        typer.echo(f"  would clone {repo} ({base_branch})")
        for p in tag_paths:
            typer.echo(f"  would set {file_rel}:{p} = {tag}")
        target = base_branch if push_mode == "direct" else deploy_branch
        typer.echo(f"  would commit and push to {target!r}")
        return

    if shutil.which("git") is None:
        raise typer.BadParameter("git not found on PATH")

    _output.stage(f"Promoting {project_name} → {environment}: {tag} (via {repo})")
    with tempfile.TemporaryDirectory(prefix="arches-gitops-") as tmp:
        clone = Path(tmp) / "repo"
        _git(["clone", "--depth", "1", "--branch", base_branch, repo, str(clone)], Path(tmp))
        target = clone / file_rel
        if not target.exists():
            raise typer.BadParameter(f"{file_rel} not found in {repo}@{base_branch}")

        yaml_rt = YAML()
        yaml_rt.preserve_quotes = True
        documents = list(yaml_rt.load_all(target.read_text(encoding="utf-8")))
        all_changes: list[tuple[str, str, str]] = []
        for dotted in tag_paths:
            changes = _set_yaml_path(documents, dotted, tag)
            if not changes:
                raise typer.BadParameter(
                    f"path {dotted!r} not found in {file_rel} — check gitops.tagPath"
                )
            all_changes += [(dotted, old, new) for old, new in changes]

        if all(old == new for _, old, new in all_changes):
            typer.echo(f"  {environment} is already at {tag} — nothing to do")
            return
        for dotted, old, new in all_changes:
            if old != new:
                typer.echo(f"  {file_rel}:{dotted}: {old} → {new}")

        with target.open("w", encoding="utf-8") as fh:
            yaml_rt.dump_all(documents, fh)

        if push_mode == "branch":
            _git(["checkout", "-b", deploy_branch], clone)
        _git(["add", str(target.relative_to(clone))], clone)
        _git(
            [
                "-c", "user.name=arches-toolkit",
                "-c", "user.email=arches-toolkit@flaxandteal.co.uk",
                "commit", "-m",
                f"deploy({project_name}): {environment} → {tag}\n\nPromoted via `arches-toolkit deploy {environment} --tag {tag}`.",
            ],
            clone,
        )
        if push_mode == "direct":
            _git(["push", "origin", base_branch], clone)
            typer.echo(f"  ✓ pushed to {base_branch} — Flux will roll {environment} out")
        else:
            # deploy/* branches are generated; force-push replaces a stale
            # attempt at the same tag rather than failing.
            _git(["push", "--force", "origin", deploy_branch], clone)
            typer.echo(f"  ✓ pushed branch {deploy_branch}")
            url = _pr_url(repo, deploy_branch)
            if url:
                typer.echo(f"  open a PR: {url}")
            typer.echo("  Flux rolls it out once merged.")


def deploy(
    environment: str = typer.Argument("dev", help="Environment name (deploy.yaml key, or built-in dev/staging/prod)"),
    project_root: Path = typer.Option(Path("."), "--project-root", show_default=False, help="Project root (default: cwd)"),
    namespace: str = typer.Option("", "--namespace", "-n", help="Target namespace (default: <project>-<env>)"),
    context: str = typer.Option("", "--context", help="kubeconfig context (default: current)"),
    image_repository: str = typer.Option("", "--image", help="Image repository (default: PROJECT_IMAGE from .env)"),
    tag: str = typer.Option("", "--tag", help="Image tag (default: PROJECT_TAG from .env)"),
    force: bool = typer.Option(False, "--force", help="Proceed even if the namespace looks Flux-managed"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the helm invocations without executing"),
    render: bool = typer.Option(False, "--render", help="helm template instead of upgrade (no cluster needed)"),
) -> None:
    """Deploy this project to a k8s environment with sensible defaults."""
    project_root = project_root.resolve()
    dotenv = _read_env_file(project_root / ".env")
    project_name = dotenv.get("PROJECT_NAME")
    if not project_name:
        raise typer.BadParameter(
            "PROJECT_NAME not found in .env — run from a toolkit project root "
            "(or pass --project-root)"
        )

    envs = _load_environments(project_root)
    if environment not in envs:
        known = ", ".join(sorted(envs))
        raise typer.BadParameter(f"unknown environment {environment!r} (known: {known})")
    spec = envs[environment]
    mode = spec.get("mode", "direct")

    if environment == "prod" and mode != "gitops":
        raise typer.BadParameter(
            "prod deploys must use gitops mode — direct helm against production "
            "is deliberately unsupported (docs/k8s-deployment.md)"
        )

    if mode == "gitops":
        gitops_cfg = spec.get("gitops") or {}
        if not gitops_cfg:
            typer.echo(f"Environment '{environment}' deploys via GitOps, not from this machine:")
            typer.echo("  1. CI publishes the image (project-ci.yml → main-<bid>, project-release.yml → vX.Y.Z).")
            typer.echo("  2. The fluxcd repo pins the tag/values for this namespace; Flux rolls it out.")
            typer.echo("  Staging follows main-* automatically; prod is a reviewed tag bump there.")
            typer.echo("")
            typer.echo("  To promote from here, configure the environment in deploy.yaml:")
            typer.echo("    environments:")
            typer.echo(f"      {environment}:")
            typer.echo("        mode: gitops")
            typer.echo("        gitops:")
            typer.echo("          repo: git@github.com:flaxandteal/<project>-fluxcd.git")
            typer.echo("          file: <path/to/helmrelease.yaml>")
            typer.echo("          tagPath: spec.values.image.tag")
            typer.echo(f"  then: arches-toolkit deploy {environment} --tag <tag>")
            raise typer.Exit(2)
        _gitops_deploy(project_name, environment, gitops_cfg, tag, dry_run=dry_run)
        return

    if shutil.which("helm") is None and not dry_run:
        raise typer.BadParameter("helm not found on PATH (https://helm.sh/docs/intro/install/)")

    ns = namespace or spec.get("namespace") or f"{project_name}-{environment}"
    kube_context = context or spec.get("context") or None
    repo = image_repository or spec.get("image", {}).get("repository") or dotenv.get("PROJECT_IMAGE", "")
    image_tag = tag or spec.get("image", {}).get("tag") or dotenv.get("PROJECT_TAG", "")
    if not repo or not image_tag:
        raise typer.BadParameter(
            "no image to deploy: pass --image/--tag, set them in deploy.yaml, "
            "or set PROJECT_IMAGE/PROJECT_TAG in .env"
        )
    if "/" not in repo:
        typer.echo(
            f"  ! image {repo!r} has no registry — the cluster must already have "
            "it (kind/k3d import); push to a registry for anything remote",
            err=True,
        )

    if not (dry_run or render) and not force and _flux_owns_namespace(ns, kube_context):
        typer.echo(
            f"✗ namespace {ns!r} carries Flux ownership labels — a direct helm "
            "deploy would fight the controller. Use the gitops path, or --force "
            "if you know this namespace is yours.",
            err=True,
        )
        raise typer.Exit(1)

    app_chart = package_data_path(APP_CHART)
    dev_services = bool(spec.get("devServices"))
    generated = _load_or_create_secrets(project_root, environment) if dev_services else {}
    services_release = f"{project_name}-services"

    if not render:
        # --render's stdout is the manifest stream; keep it clean.
        _output.stage(f"Deploying {project_name} → {environment} (namespace {ns})")

    with tempfile.TemporaryDirectory(prefix="arches-deploy-") as tmp:
        tmpdir = Path(tmp)

        if dev_services:
            svc_values = {
                "postgres": {"password": generated["pgPassword"]},
                "rabbitmq": {"password": generated["rabbitmqPassword"]},
            }
            svc_values_file = tmpdir / "services.values.yaml"
            svc_values_file.write_text(yaml.safe_dump(svc_values), encoding="utf-8")
            _run(
                _helm_argv(
                    services_release,
                    package_data_path(DEV_SERVICES_CHART),
                    ns, kube_context, [svc_values_file], render=render,
                ),
                dry_run=dry_run,
            )
            if not (dry_run or render):
                typer.echo("  ✓ backing services ready (postgres, elasticsearch, rabbitmq)")

        app_values: dict = {
            # Deterministic resource names (<project>-web, <project>-init, …)
            # whatever the project is called.
            "fullnameOverride": project_name,
            "project": {"package": dotenv.get("PROJECT_PACKAGE") or project_name},
            "image": {"repository": repo, "tag": image_tag},
        }
        if dev_services:
            app_values = _deep_merge(app_values, {
                "postgres": {
                    "host": f"{services_release}-db",
                    "existingSecret": f"{services_release}-db",
                    "existingSecretKey": "password",
                },
                "elasticsearch": {"host": f"{services_release}-elasticsearch"},
                "rabbitmq": {
                    "existingSecret": f"{services_release}-rabbitmq",
                    "existingSecretKey": "rabbitmq-url",
                },
                "secretEnv": {"DJANGO_SECRET_KEY": generated["djangoSecretKey"]},
            })
        app_values = _deep_merge(app_values, spec.get("values") or {})

        values_files: list[Path] = []
        profile = spec.get("profile")
        if profile:
            values_files.append(app_chart / f"values-{profile}.yaml")
        app_values_file = tmpdir / "app.values.yaml"
        app_values_file.write_text(yaml.safe_dump(app_values), encoding="utf-8")
        values_files.append(app_values_file)

        _run(
            _helm_argv(project_name, app_chart, ns, kube_context, values_files, render=render),
            dry_run=dry_run,
        )

    if dry_run or render:
        return

    _output.stage("Deployed")
    typer.echo(f"    kubectl -n {ns} get pods")
    typer.echo(f"    kubectl -n {ns} port-forward svc/{project_name}-web 8000:8000")
    typer.echo(f"    (init job logs: kubectl -n {ns} logs job/{project_name}-init)")
