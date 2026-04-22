"""``arches-toolkit create`` — scaffold widgets, plugins, apps, and friends.

Each subcommand renders a template tree from
``_data/templates/<arches-major-minor>/<kind>/`` into the resolved target.
Registration (``manage.py <kind> register -s …``) is never run — the
command echoes the exact invocation, matching ``init``'s pattern.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .. import scaffold
from .._util import validate_name

app = typer.Typer(
    no_args_is_help=True,
    help="Scaffold widgets, components, plugins, and full Arches applications",
)


# --------------------------------------------------------------------------- #
# Shared option parsing
# --------------------------------------------------------------------------- #


def _resolve(
    *,
    app_dir: Optional[Path],
    arches_version: Optional[str],
) -> scaffold.Target:
    try:
        return scaffold.resolve_target(
            cwd=Path.cwd(),
            app_dir=app_dir,
            arches_version=arches_version,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from None


def _write_dir_for(target: scaffold.Target) -> Path:
    """Where files for the selected ``target`` should be rooted."""
    if target.is_app:
        return target.root / target.package
    return target.root


def _render(
    *,
    target: scaffold.Target,
    kind: str,
    tokens: dict[str, str],
    force: bool,
    with_knockout: bool,
) -> list[Path]:
    written: list[Path] = []
    write_dir = _write_dir_for(target)

    try:
        base = scaffold.template_root(target.arches_version, kind)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from None

    try:
        written.extend(scaffold.render_and_write(base, write_dir, tokens, force=force))
    except FileExistsError as exc:
        raise typer.BadParameter(str(exc)) from None

    if with_knockout:
        try:
            ko_root = scaffold.template_root(
                target.arches_version, f"{kind}.knockout"
            )
        except FileNotFoundError:
            typer.echo(f"note: no knockout variant for {kind} at {target.arches_version}")
        else:
            try:
                written.extend(
                    scaffold.render_and_write(ko_root, write_dir, tokens, force=force)
                )
            except FileExistsError as exc:
                raise typer.BadParameter(str(exc)) from None
    return written


def _echo_written(written: list[Path]) -> None:
    for p in written:
        try:
            rel = p.relative_to(Path.cwd())
        except ValueError:
            rel = p
        typer.echo(f"wrote {rel}")


def _echo_next(target: scaffold.Target, cmd: str | None, artifact_path: Path | None) -> None:
    typer.echo("")
    typer.echo("Next:")
    if cmd and artifact_path:
        try:
            rel = artifact_path.relative_to(Path.cwd())
        except ValueError:
            rel = artifact_path
        typer.echo(f"  arches-toolkit exec web python manage.py {cmd} register -s {rel}")
    if target.is_app:
        typer.echo(
            f"  # target is the arches-{target.package.removeprefix('arches_')} app; "
            "rebuild/publish it to apply"
        )


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


# Common option factories keep help text uniform without duplicating strings.
def _opt_app() -> Optional[Path]:
    return typer.Option(
        None, "--app", help="Write into an existing Arches application package"
    )


def _opt_version() -> Optional[str]:
    return typer.Option(
        None, "--arches-version", help="Override Arches major.minor for template selection"
    )


def _opt_knockout() -> bool:
    return typer.Option(False, "--knockout", help="Also emit legacy Knockout shim files")


def _opt_force() -> bool:
    return typer.Option(False, "--force", help="Overwrite existing files")


@app.command("widget", help="Scaffold a form widget (JSON + Vue3 component)")
def widget(
    name: str = typer.Argument(..., help="Widget name (snake_case)"),
    datatype: str = typer.Option("string", "--datatype", help="Datatype this widget edits"),
    app_dir: Optional[Path] = _opt_app(),
    arches_version: Optional[str] = _opt_version(),
    knockout: bool = _opt_knockout(),
    force: bool = _opt_force(),
) -> None:
    validate_name(name, what="widget name")
    target = _resolve(app_dir=app_dir, arches_version=arches_version)
    tokens = scaffold.derive_tokens(name, package=target.package, datatype=datatype)
    written = _render(
        target=target, kind="widget", tokens=tokens, force=force, with_knockout=knockout
    )
    _echo_written(written)
    artifact = _write_dir_for(target) / "widgets" / f"{name}.json"
    _echo_next(target, "widget", artifact)


@app.command("card-component", help="Scaffold a card component (JSON + Vue3 component)")
def card_component(
    name: str = typer.Argument(..., help="Card component name (snake_case)"),
    app_dir: Optional[Path] = _opt_app(),
    arches_version: Optional[str] = _opt_version(),
    knockout: bool = _opt_knockout(),
    force: bool = _opt_force(),
) -> None:
    validate_name(name, what="card component name")
    target = _resolve(app_dir=app_dir, arches_version=arches_version)
    tokens = scaffold.derive_tokens(name, package=target.package)
    written = _render(
        target=target, kind="card-component", tokens=tokens, force=force, with_knockout=knockout
    )
    _echo_written(written)
    artifact = _write_dir_for(target) / "card_components" / f"{name}.json"
    _echo_next(target, "card_component", artifact)


@app.command("plugin", help="Scaffold a sidebar plugin page")
def plugin(
    name: str = typer.Argument(..., help="Plugin name (snake_case)"),
    slug: Optional[str] = typer.Option(None, "--slug", help="URL slug (defaults to name with dashes)"),
    icon: str = typer.Option("fa fa-puzzle-piece", "--icon", help="FontAwesome icon class"),
    app_dir: Optional[Path] = _opt_app(),
    arches_version: Optional[str] = _opt_version(),
    knockout: bool = _opt_knockout(),
    force: bool = _opt_force(),
) -> None:
    validate_name(name, what="plugin name")
    target = _resolve(app_dir=app_dir, arches_version=arches_version)
    tokens = scaffold.derive_tokens(
        name,
        package=target.package,
        slug=slug or name.replace("_", "-"),
        icon=icon,
    )
    written = _render(
        target=target, kind="plugin", tokens=tokens, force=force, with_knockout=knockout
    )
    _echo_written(written)
    artifact = _write_dir_for(target) / "plugins" / f"{name}.json"
    _echo_next(target, "plugin", artifact)


@app.command("report", help="Scaffold a report template")
def report(
    name: str = typer.Argument(..., help="Report name (snake_case)"),
    app_dir: Optional[Path] = _opt_app(),
    arches_version: Optional[str] = _opt_version(),
    force: bool = _opt_force(),
) -> None:
    validate_name(name, what="report name")
    target = _resolve(app_dir=app_dir, arches_version=arches_version)
    tokens = scaffold.derive_tokens(name, package=target.package)
    # Reports are Knockout-only in both 7.6 and 8.1 — no Vue3 variant yet.
    written = _render(
        target=target, kind="report", tokens=tokens, force=force, with_knockout=False
    )
    _echo_written(written)
    artifact = _write_dir_for(target) / "reports" / f"{name}.json"
    _echo_next(target, "report", artifact)


@app.command("function", help="Scaffold a node / primary-descriptor function")
def function(
    name: str = typer.Argument(..., help="Function name (snake_case)"),
    function_type: str = typer.Option(
        "node", "--type", help="Function type: node or primarydescriptors"
    ),
    class_name: Optional[str] = typer.Option(
        None, "--class-name", help="Python class name (defaults to PascalCase of name)"
    ),
    with_ui: bool = typer.Option(False, "--with-ui", help="Also emit Knockout config UI"),
    app_dir: Optional[Path] = _opt_app(),
    arches_version: Optional[str] = _opt_version(),
    force: bool = _opt_force(),
) -> None:
    validate_name(name, what="function name")
    target = _resolve(app_dir=app_dir, arches_version=arches_version)
    tokens = scaffold.derive_tokens(
        name,
        package=target.package,
        function_type=function_type,
        class_name=class_name or "",
    )
    if not tokens["class_name"]:
        tokens["class_name"] = tokens["NameCamel"]
    written = _render(
        target=target, kind="function", tokens=tokens, force=force, with_knockout=with_ui
    )
    _echo_written(written)
    artifact = _write_dir_for(target) / "functions" / f"{name}.py"
    _echo_next(target, "fn", artifact)


@app.command("datatype", help="Scaffold a custom datatype Python module")
def datatype(
    name: str = typer.Argument(..., help="Datatype name (snake_case)"),
    class_name: Optional[str] = typer.Option(
        None, "--class-name", help="Python class name (defaults to PascalCase of name)"
    ),
    app_dir: Optional[Path] = _opt_app(),
    arches_version: Optional[str] = _opt_version(),
    force: bool = _opt_force(),
) -> None:
    validate_name(name, what="datatype name")
    target = _resolve(app_dir=app_dir, arches_version=arches_version)
    tokens = scaffold.derive_tokens(
        name, package=target.package, class_name=class_name or ""
    )
    if not tokens["class_name"]:
        tokens["class_name"] = tokens["NameCamel"]
    written = _render(
        target=target, kind="datatype", tokens=tokens, force=force, with_knockout=False
    )
    _echo_written(written)
    artifact = _write_dir_for(target) / "datatypes" / f"{name}.py"
    _echo_next(target, "datatype", artifact)


@app.command("search-filter", help="Scaffold a search filter component")
def search_filter(
    name: str = typer.Argument(..., help="Search filter name (snake_case)"),
    filter_type: str = typer.Option("filter", "--type", help="filter or popup"),
    class_name: Optional[str] = typer.Option(
        None, "--class-name", help="Python class name (defaults to PascalCase of name)"
    ),
    app_dir: Optional[Path] = _opt_app(),
    arches_version: Optional[str] = _opt_version(),
    force: bool = _opt_force(),
) -> None:
    validate_name(name, what="search filter name")
    target = _resolve(app_dir=app_dir, arches_version=arches_version)
    tokens = scaffold.derive_tokens(
        name,
        package=target.package,
        filter_type=filter_type,
        class_name=class_name or "",
    )
    if not tokens["class_name"]:
        tokens["class_name"] = tokens["NameCamel"]
    written = _render(
        target=target, kind="search-filter", tokens=tokens, force=force, with_knockout=False
    )
    _echo_written(written)
    artifact = _write_dir_for(target) / "search_components" / f"{name}.py"
    _echo_next(target, "search", artifact)


@app.command("component", help="Scaffold a plain Vue3 component (no Arches registration)")
def component(
    name: str = typer.Argument(..., help="Component name (snake_case)"),
    app_dir: Optional[Path] = _opt_app(),
    arches_version: Optional[str] = _opt_version(),
    force: bool = _opt_force(),
) -> None:
    validate_name(name, what="component name")
    target = _resolve(app_dir=app_dir, arches_version=arches_version)
    tokens = scaffold.derive_tokens(name, package=target.package)
    written = _render(
        target=target, kind="component", tokens=tokens, force=force, with_knockout=False
    )
    _echo_written(written)
    _echo_next(target, None, None)


@app.command("app", help="Scaffold a new arches-<name> pip-installable application")
def app_cmd(
    name: str = typer.Argument(..., help="App name — the 'foo' in arches-foo (snake_case)"),
    path: Optional[Path] = typer.Option(
        None, "--path", help="Parent dir to create arches-<name>/ under (default: cwd)"
    ),
    arches_version: Optional[str] = typer.Option(
        None, "--arches-version", help="Arches major.minor for template selection"
    ),
    force: bool = _opt_force(),
) -> None:
    validate_name(name, what="app name")
    parent = (path or Path.cwd()).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    app_root = parent / f"arches-{name.replace('_', '-')}"

    # No existing-target check needed; render_and_write refuses to overwrite
    # without --force. But do refuse creating a sibling that exists and is
    # non-empty as a courtesy, matching init.
    if app_root.exists() and any(app_root.iterdir()) and not force:
        raise typer.BadParameter(
            f"{app_root}: exists and is non-empty — pass --force to scaffold inside it"
        )
    app_root.mkdir(parents=True, exist_ok=True)

    version = scaffold.detect_arches_version(
        explicit=arches_version, project_root=app_root
    )
    try:
        template = scaffold.template_root(version, "app")
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc)) from None

    tokens = scaffold.derive_tokens(
        name,
        package=f"arches_{name}",
    )
    try:
        written = scaffold.render_and_write(template, app_root, tokens, force=force)
    except FileExistsError as exc:
        raise typer.BadParameter(str(exc)) from None
    _echo_written(written)

    typer.echo("")
    typer.echo("Next:")
    try:
        rel_root = app_root.relative_to(Path.cwd())
    except ValueError:
        rel_root = app_root
    typer.echo(f"  pip install -e {rel_root}")
    typer.echo(
        f"  arches-toolkit add-app arches-{name.replace('_', '-')} "
        f"--source path --path {rel_root}"
    )
