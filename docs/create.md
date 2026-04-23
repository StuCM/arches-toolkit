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
`source: pypi, mode: develop` as a placeholder. Opt out with `--no-register`.

### Install shapes the toolkit handles

| `source` | `mode` | In pyproject? | Overlay mount? | Use case |
|---|---|---|---|---|
| `pypi` / `git` | `release` | yes | no | Normal dep, install from remote, don't edit locally |
| `pypi` / `git` | `develop` | yes | yes | Install from remote + overlay clone source for live editing |

Release-mode apps live only in pyproject. Develop-mode apps go through
pyproject **and** get a bind mount so your clone's edits overlay the
install. Every app needs a real installable source — there is no "local
filesystem only" mode today. See **Known limitation** below.

### Brand-new scaffolded app flow

```bash
# 1. From the project root, scaffold the app as a sibling dir.
#    Auto-registers as source: pypi (placeholder), mode: develop.
arches-toolkit create app file_uploader --path ..

# 2. ⚠ STOP — the app isn't on PyPI yet, so `sync-apps` will fail unless
#    you fix the source first. Pick one:
#
#    (a) Push the scaffold to git, then edit apps.yaml:
#        source: git
#        repo: <your-git-url>
#        ref: main
#        path: arches-file-uploader
#
#    (b) Hand-edit pyproject.toml to add:
#        "arches-file-uploader @ file:///absolute/path/to/arches-file-uploader"
#        (Option b makes your uv.lock machine-specific — don't commit it
#        until you've moved to (a).)

# 3. After fixing the source, propagate apps.yaml through the rest:
arches-toolkit sync-apps
#    - Regenerates pyproject.toml + compose.apps.yaml
#    - Regenerates uv.lock automatically
#    - Updates INSTALLED_APPS managed section in settings.py

# 4. Rebuild so uv sync installs the app + deps in the image.
arches-toolkit down
arches-toolkit dev --build

# 5. Edit the app's code freely — bind-mounted, changes are live.
```

### Known limitation: brand-new filesystem-only apps

A "local-only" mode where scaffolded apps could be used via bind mount
without any installable source would be ideal but isn't feasible today:
Arches 8.1's `check_arches_compatibility` system check requires
`importlib.metadata` to find the app's package metadata, which doesn't
exist for bind-mounted-only packages. See
[TASKS.md](../TASKS.md) "Open design problem: scaffolded local-only apps"
— this is a real gap we want to close. For now, scaffolded apps need to
either be pushed to git or referenced by file:// URL in pyproject.toml.

### Promoting local → git (when you're ready to share)

Once you push the scaffold to a git repo, flip the source:

```yaml
# apps.yaml — change from:
- package: arches-file-uploader
  source: local
  mode: develop
  path: arches-file-uploader

# to:
- package: arches-file-uploader
  source: git
  repo: https://github.com/your-org/arches-file-uploader.git
  ref: main
  mode: develop         # keep develop to maintain the overlay
  path: arches-file-uploader
```

```bash
arches-toolkit sync-apps    # sync-apps auto-runs uv lock
arches-toolkit down && arches-toolkit dev --build
```

Now the app is installed from git (via uv sync) AND overlaid by your
local clone. Your CI and teammates get the installable version; you
keep the live-editing loop.

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
