# `arches-toolkit create`

Scaffold Arches artifacts — widgets, card components, plugins, reports,
functions, datatypes, search filters, plain Vue components, and whole
pip-installable applications — with version-aware templates. The command
never runs `manage.py register` for you; it echoes the exact invocation so
you can run it inside the web container when ready.

## Shape

```
arches-toolkit create <kind> <name> [options]
```

Kinds and the files each writes (assuming default project target with
package `mything`):

| Kind | Primary outputs | With `--knockout` |
|---|---|---|
| `widget` | `widgets/<name>.json`<br>`src/mything/components/widgets/<NameCamel>Widget.vue` | + `templates/views/components/widgets/<name>.htm`<br>+ `media/js/views/components/widgets/<name>.js` |
| `card-component` | `card_components/<name>.json`<br>`src/mything/components/cards/<NameCamel>Card.vue` | + KO HTM + JS |
| `plugin` | `plugins/<name>.json`<br>`src/mything/pages/<NameCamel>.vue` | + KO HTM + JS |
| `report` | `reports/<name>.json` + JS + HTM *(KO-only in both 7.6 and 8.1)* | n/a |
| `function` | `functions/<name>.py` | *(`--with-ui`)* + KO config HTM + JS |
| `datatype` | `datatypes/<name>.py` | n/a |
| `search-filter` | `search_components/<name>.py` + KO JS + HTM | n/a |
| `component` | `src/mything/components/<NameCamel>.vue` | n/a |
| `app` | `arches-<name>/` sibling directory — see below | n/a |

## Targeting

- Default: write into the current project. The project is identified via
  `PROJECT_PACKAGE` in `.env` (or the convention of a package dir named
  after the cwd that contains `settings.py`).
- `--app <dir>`: write into an existing Arches application package. The
  directory must contain `arches_<name>/apps.py` whose `AppConfig` sets
  `is_arches_application = True`. Files nest under `<dir>/arches_<name>/`,
  matching arches-lingo's layout.
- `create app <name>`: create a brand-new `arches-<name>/` tree as a
  sibling dir of the current project (override parent with `--path`).

## Versioning

Templates live under `cli/src/arches_toolkit/_data/templates/<major.minor>/`.
Today we ship sets for **8.1** (Vue3-first) and **7.6** (Knockout-first).

Version selection, first match wins:

1. `--arches-version <X.Y>` flag
2. `arches` requirement in the target's `pyproject.toml`
3. `ARCHES_VERSION` environment variable
4. Latest packaged template set

If the picked version has no exact template set, the closest lower set is
used with a warning. To add a new version, create
`_data/templates/<new-version>/<kind>/` dirs — no code changes needed.

## Placeholders

Template files carry a `.tmpl` suffix (stripped on write). Paths and
contents go through `string.Template`, so `${name}` / `${package}` /
`${NameCamel}` / `${uuid}` etc. resolve in filenames and inside files.

The token set:

| Token | Derived from |
|---|---|
| `${name}` | The positional `<name>` arg (snake_case required) |
| `${NameCamel}` | PascalCase of `${name}` |
| `${nameCamel}` | camelCase of `${name}` |
| `${package}` | Target Python package (e.g. `mything`, `arches_demo`) |
| `${package_dashed}` | `${name}` with `_` → `-` |
| `${uuid}` | A fresh UUID4, one per render |
| `${slug}` | Plugin slug (defaults to `${package_dashed}`) |
| `${icon}` | Plugin icon class (defaults to `fa fa-puzzle-piece`) |
| `${datatype}` | Widget datatype (defaults to `string`) |
| `${class_name}` | Python class name for datatype/function/search-filter |
| `${function_type}` | `node` or `primarydescriptors` |
| `${filter_type}` | Search filter `filter` or `popup` |

## Register commands echoed

After writing, the command prints the exact `manage.py register` invocation.
Run it inside the web container when your stack is up:

```bash
arches-toolkit dev
arches-toolkit exec web python manage.py widget register -s widgets/my_widget.json
```

Register commands by kind: `widget`, `card_component`, `plugin`, `report`,
`fn` *(function)*, `datatype`, `search`.

The `component` kind has no register step — it's just a Vue file.

## `create app` lifecycle

`create app` does more than scaffold — if run inside a project (cwd has
`apps.yaml`), it also **auto-registers** the new app in `apps.yaml` with
`mode: develop`. Opt out with `--no-register`.

The full lifecycle for a new sibling-app you want to build incrementally
inside your project's dev stack:

```bash
# 1. From the project root, scaffold the app as a sibling directory.
#    apps.yaml is updated automatically with mode: develop.
arches-toolkit create app file_uploader --path .. --arches-version 7.6

# 2. Generate compose.apps.yaml with the bind mount for the new app.
arches-toolkit sync-apps

# 3. Recreate containers so the new volume mount takes effect.
#    (A plain `restart` won't pick up new volumes — compose has to recreate.)
arches-toolkit down
arches-toolkit dev

# 4. Install the new app editable in the container venv.
#    Required until the develop-mode install gap is closed — see below.
arches-toolkit exec web uv pip install -e /opt/apps/arches-file-uploader
arches-toolkit restart web worker

# 5. Edit the app's code freely — bind-mounted, no further actions needed.
#    Django autoreload picks up Python changes; webpack HMR picks up frontend.
```

After step 4 the app is importable as `arches_file_uploader`. Add it to
`INSTALLED_APPS` (either in the project's settings, or it may already be
auto-discovered depending on your setup), use its widgets/datatypes/etc.

### Why you don't need `--build`

`arches-toolkit dev --build` rebuilds the Docker image. Nothing in the image
changes when you add a develop-mode app — the app's code is bind-mounted, not
baked in. A rebuild is wasted work. Only rebuild when you change the toolkit
base image, the project Dockerfile, or the project's `pyproject.toml` pins.

### Known gap: the container-side install

Develop-mode apps are bind-mounted at `/opt/apps/<dirname>` by `sync-apps`,
but the toolkit does not yet automatically `uv pip install -e` them into the
container venv. Without step 4, Django will throw
`ModuleNotFoundError: No module named 'arches_<name>'` when it tries to import
the app.

The install survives container restarts but not `arches-toolkit down -v`
(which wipes the venv volume). After a `down -v`, redo step 4.

Planned fix (tracked in `TASKS.md`): the dev-stage entrypoint will `pip install
-e` every directory under `/opt/apps/` at container start, making this seamless.

### Promoting from develop to release

When your sibling-app stabilises and you want it installed from PyPI or a
pinned git ref instead of bind-mounted, edit its entry in `apps.yaml`:

```yaml
# before
- package: arches-file-uploader
  source: pypi
  mode: develop

# after
- package: arches-file-uploader
  source: pypi
  version: ">=0.1.0"
  mode: release
```

Or for a git source:

```yaml
- package: arches-file-uploader
  source: git
  repo: https://github.com/you/arches-file-uploader.git
  ref: v0.1.0
  mode: release
```

Then `arches-toolkit sync-apps` removes the bind mount from `compose.apps.yaml`
and adds the dep to `pyproject.toml`. A `dev --build` installs it at image
build time.

### About `source: pypi` on a freshly-scaffolded app

`create app` registers with `source: pypi` by default. This is a placeholder —
for `mode: develop` entries, sync-apps doesn't consult the `source` field at
all (the bind mount dirname is derived from the package name instead). When
you eventually promote to `mode: release`, update `source` + add a `version`
or `repo`/`ref` — otherwise sync-apps will emit a PEP 508 line for a package
PyPI doesn't have.

## Extending templates

To ship a new kind (or fork behaviour for a specific Arches version):

1. Drop files under `cli/src/arches_toolkit/_data/templates/<X.Y>/<kind>/`.
   Use `${…}` for substitutions and a `.tmpl` suffix on every file whose
   content must be rendered (non-`.tmpl` files are copied verbatim).
2. Add a Typer command in `cli/src/arches_toolkit/commands/create.py` —
   mirror an existing one, call `scaffold.derive_tokens(…)` plus
   `_render(…)`, then `_echo_next(…)`.
3. Write a test in `cli/tests/test_scaffold.py` that calls
   `render_and_write` against the new template dir and asserts expected
   paths.

## Idempotency

Scaffolding refuses to overwrite existing files. Pass `--force` to
overwrite. The overwrite check is run up-front, so a conflict aborts
before any file is written.
