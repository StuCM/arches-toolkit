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

The `app` kind emits `pip install -e <path>` plus an `arches-toolkit
add-app --source path` line so the new app is wired into the project.

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
