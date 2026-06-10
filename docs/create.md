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

`create app` scaffolds the app as its own git repository (with a first
commit) but does **not** register it in `apps.yaml`. That's deliberate:
everything in `apps.yaml` must be installable by any teammate — `sync-apps`
runs `uv lock`, which resolves develop entries as `pkg @ git+repo@ref`, so
the repo must exist *and* the ref must be pushed before an entry can work.
Registration is one `add-app` away once you've pushed.

Run from a project root (cwd has `apps.yaml`), the scaffold lands as a
**sibling** of the project — the location the `/workspace` mount and
`add-app`'s clone convention expect. `--path` overrides; outside a project
it scaffolds into cwd.

### Install shapes the toolkit handles

| `source` | `mode` | In pyproject? | Overlay mount? | Use case |
|---|---|---|---|---|
| `pypi` / `git` | `release` | yes | no | Normal dep, install from remote, don't edit locally |
| `pypi` / `git` | `develop` | yes | yes | Install from remote + overlay clone source for live editing |

Release-mode apps live only in pyproject. Develop-mode apps go through
pyproject **and** get the editable `/workspace` overlay so your clone's
edits are live. Every app needs a real installable source — there is
deliberately no "local filesystem only" mode (see **Why no local-only
mode** below).

### Brand-new scaffolded app flow

```bash
# 1. From the project root — scaffolds ../arches-file-uploader and
#    git-inits it with a first commit on main.
arches-toolkit create app file_uploader

# 2. Create a remote and push (one-off; any host works):
git -C ../arches-file-uploader remote add origin git@github.com:your-org/arches-file-uploader.git
git -C ../arches-file-uploader push -u origin main

# 3. Register — add-app sees the sibling dir already exists (your scaffold
#    IS the working tree), then chains sync-apps + install:
arches-toolkit add-app arches-file-uploader --source git --repo git@github.com:your-org/arches-file-uploader.git --mode develop

# 4. Edit the app's code freely — the /workspace overlay makes changes live.
```

### Why no local-only mode

Two hard constraints rule out registering an app that exists only on your
disk:

- `sync-apps` runs `uv lock`, and uv resolves `git+repo@ref` deps by
  fetching the ref — an unpushed scaffold fails the lock for the whole
  project. `file://` or absolute-path sources lock, but bake your machine's
  paths into the committed `uv.lock`, breaking everyone else's sync.
- `apps.yaml` and the managed INSTALLED_APPS block in `settings.py` are
  committed. Any entry referencing code only you have crashes every other
  machine's Django at startup (`ModuleNotFoundError`) — no install
  mechanism can fetch code that was never pushed.

So the invariant is: **registered ⇒ pushed**. `create app` makes the gap
as small as possible — the scaffold is already a git repo with a commit;
you add a remote, push, and `add-app --repo` does the rest.

### Early-stages git-published app (e.g. arches-her on a dev branch)

You already have a remote; you just want to work on a branch live:

```bash
# 1. Clone the app somewhere (typically sibling of project).
cd /path/to/project-parent
git clone https://github.com/archesproject/arches-her.git 2.0.x -b dev/2.0.x

# 2. Register in apps.yaml (by hand, or via `arches-toolkit add-app`):
```

```yaml
- package: arches-her
  source: git
  repo: https://github.com/archesproject/arches-her.git
  ref: dev/2.0.x
  mode: develop
  path: 2.0.x           # optional: when the clone dir name differs from the repo name
```

```bash
# 3. Normal sync-apps + rebuild
arches-toolkit sync-apps
arches-toolkit down && arches-toolkit dev --build

# 4. Add to INSTALLED_APPS in settings.py if needed
```

### Clones under a non-default directory name

By default `sync-apps` derives the sibling dirname from the repo URL
(e.g. `.../arches-her.git` → `../arches-her/`). If your clone is checked
out under a different name — for example you keep multiple branches as
sibling clones named by the branch — add `path:` to the apps.yaml entry:

```yaml
- package: arches-her
  source: git
  repo: https://github.com/archesproject/arches-her.git
  ref: dev/2.0.x
  mode: develop
  path: 2.0.x
```

Precedence used by `_develop_repo_dirname`: explicit `path` → repo-derived
name → `package` fallback. If the path is wrong, the bind mount either
surfaces an empty dir (wrong path) or the wrong clone's source — Python
imports then fall through to whatever the install placed in site-packages.

### Why you need `--build` the first time

`arches-toolkit dev --build` rebuilds the image so `uv sync` picks up the
new dep (for pypi/git sources) or compose picks up the new volume (for
local sources). Subsequent edits to the app's source don't need a rebuild
— the overlay makes them live. Only rebuild when you change
`pyproject.toml`, `uv.lock`, or the toolkit's Dockerfile.

### The toolkit-managed INSTALLED_APPS section

`sync-apps` keeps a clearly-marked section **inside** your `INSTALLED_APPS`
tuple/list. The entries are ordinary members of the list — no runtime
extension, no separate identifier, no magic. Any tool that reads the
literal (linters, CI inspectors, `manage.py check`, your code editor's
autocomplete) sees the full list directly:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "my.custom.app",
    # arches-toolkit:installed-apps-start
    # Managed by arches-toolkit sync-apps — do not edit between
    # these markers. To remove an app, drop it from apps.yaml
    # and re-run sync-apps.
    "arches_controlled_lists",
    "arches_her",
    "arches_my_new_app",
    # arches-toolkit:installed-apps-end
]
```

Notes on behaviour:

- **Idempotent.** Re-running `sync-apps` with the same apps.yaml regenerates
  the section identically — no diff, no churn.
- **Manual entries preserved.** Anything you write outside the markers is
  left exactly as-is. If you want to control an Arches app's position in
  the list or remove it from toolkit management, declare it outside the
  markers and remove it from `apps.yaml`.
- **Works with list or tuple form.** `INSTALLED_APPS = [...]` and
  `INSTALLED_APPS = (...)` are both supported.
- **Only the top-level literal is touched.** If your settings do
  `if DEBUG: INSTALLED_APPS += [...]` below the main assignment, those
  are left alone — they still run normally.
- **Opt out** with `arches-toolkit sync-apps --no-installed-apps` if you'd
  prefer to manage `INSTALLED_APPS` entirely by hand.

The toolkit deliberately doesn't use a runtime-extension block (e.g.
`try: INSTALLED_APPS += _MANAGED except NameError: ...`). That pattern
would hide entries from static analysis and CI introspection tools that
parse settings.py without executing it.

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

Then `arches-toolkit sync-apps` rewrites the dep in `pyproject.toml` and the
next `install` drops the editable `/workspace` override, so the app installs
from the released `git+url@ref` instead. A `dev --build` bakes it in at image
build time.

### About `source` on develop-mode entries

For `mode: develop` entries the install always comes from `git+repo@ref`
(plus the editable overlay where a clone exists) regardless of `source` —
`source` records the *release-mode* origin only. Register scaffolded apps
with `--source git` so a later switch to release installs from the repo;
use `--source pypi` for apps whose releases genuinely come from PyPI.

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
