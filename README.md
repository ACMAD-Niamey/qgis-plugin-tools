# ACMAD Tools -- QGIS plugin

A small, extensible toolbox of QGIS 3.x plugins for ACMAD backend
workflows. Each tool lives in its own subpackage under `tools/` and shares
a common "ACMAD Tools" toolbar/menu and backend connection settings
(server base URL + API token), so future tools can be added without
duplicating that plumbing.

The first (and currently only) tool is **Forecast Ingest**: it lets a
domain expert upload a drought forecast polygon shapefile directly from
QGIS to the ACMAD Drought Advisory backend's REST API, instead of a
manual out-of-band upload process.

The plugin code lives in the [`acmad_tools/`](./acmad_tools)
directory -- that directory *is* the installable QGIS plugin.

## What the Forecast Ingest tool does

1. You pick a forecast polygon shapefile, either as a `.shp` file from
   disk (its `.shx`/`.dbf`/`.prj`/`.cpg` sidecar files must be alongside
   it) or as a polygon layer already loaded in the current QGIS project
   (must have an integer `fcst_cat` field; exported to a temporary
   shapefile, reprojected to EPSG:4326, before upload).
2. You fill in the forecast metadata: forecast period (one of the 12
   rolling three-month codes, e.g. `JAS`), a free-text lead name, the date
   the forecast was produced, the reference year, and two flags
   (`cleanup`, `update_latest`).
3. The plugin zips the shapefile parts client-side and POSTs them, plus the
   metadata, as `multipart/form-data` to:

   ```
   POST {server_base_url}/api/data_api/data_upload/forecast/
   ```

   authenticated with a DRF API token sent as an `Authorization: Token
   <key>` header.
4. The upload runs asynchronously (Qt's own network stack -- no blocking
   of the QGIS UI thread), with a progress bar, and the backend's
   `{"status": "success"|"error", "message": "..."}` response is shown via
   the QGIS message bar.

If a file-on-disk shapefile's `.prj` CRS is not `EPSG:4326` (WGS84), the
plugin shows a non-blocking warning but still allows the upload -- it does
**not** reproject that path. Loaded-layer input is always reprojected to
EPSG:4326 on export, so this warning never applies to it. Any kind of
self-service login/token-issuing flow remains explicitly out of scope for
this first version.

## Installation

1. Build an installable zip by running `./scripts/package.sh` from the
   repo root -- it produces `dist/acmad_tools-<version>.zip` with the
   `acmad_tools/` directory as the zip's top-level entry (required for
   QGIS's "Install from ZIP" to work). This is the same script the release
   workflow uses, so a locally built zip matches exactly what a GitHub
   Release ships.

   If you'd rather not run the script, zipping the folder manually works
   too (the zip's top-level entry must still be the `acmad_tools`
   directory): `cd acmad_tools && zip -r ../acmad_tools.zip . -x '.*'`, or
   just zip the folder in Finder/Explorer.
2. In QGIS: **Plugins -> Manage and Install Plugins... -> Install from
   ZIP**, select the zip file, click **Install Plugin**.
3. Enable the plugin if it isn't auto-enabled (**Plugins -> Manage and
   Install Plugins... -> Installed**, check "ACMAD Tools").
4. A shared "ACMAD Tools" toolbar and a **Plugins -> ACMAD Tools** menu
   appear, with one entry per available tool (currently just "Upload
   Forecast to ACMAD...").

## Releasing

- **CI** (`.github/workflows/ci.yml`) runs automatically on every push and
  pull request targeting `main`. It's a fast, cheap safety net: Python
  syntax/import validity across `acmad_tools/`, `.ui` file XML
  well-formedness, and a smoke test that `scripts/package.sh` runs
  cleanly. It does **not** exercise any PyQGIS/PyQt5 runtime behaviour --
  see "Known limitations" below.
- **To cut a release**: bump `version=` in `acmad_tools/metadata.txt`,
  commit, tag that commit `vX.Y.Z` matching the new version exactly (e.g.
  `v0.1.1`), and push the tag. The release workflow
  (`.github/workflows/release.yml`) then verifies the tag matches
  `metadata.txt`, builds the zip via `scripts/package.sh`, and publishes a
  GitHub Release with the zip attached and auto-generated release notes.
- **Manual/local packaging without releasing**: run `./scripts/package.sh`
  any time to produce the same zip locally -- useful for testing an
  install before cutting a real release. The release workflow can also be
  triggered manually (`workflow_dispatch`, no tag needed) to build and
  upload a sanity-check zip as a workflow artifact.

## Getting an API token

There is no self-service sign-up. A backend administrator issues you a
token out-of-band (Django admin, or the management command below run on
the server):

```
python manage.py default_api_token_generation <username>
```

Paste that token into the plugin's Settings dialog (see below) -- it is
stored locally via QGIS's `QSettings` (organisation `ACMAD`, application
`ForecastIngestPlugin`) and reused for every upload. This settings store
is shared infrastructure (`acmad_tools/core/settings_manager.py`): future
tools that also talk to the ACMAD backend are expected to reuse the same
base URL/token rather than prompting for their own.

## Using the Forecast Ingest tool

1. Click the toolbar icon (or **Plugins -> ACMAD Tools -> Upload Forecast
   to ACMAD...**).
2. Click **Settings...** (first time only, or whenever the server URL /
   token changes): enter the server base URL (e.g.
   `https://acmad-drought.example.org`, no trailing slash needed) and the
   API token, then click **Test Connection** to confirm both the URL and
   the token are correct before saving.
3. Back in the main dialog, pick the forecast shapefile from either
   source:
   - **File on disk** (default): **Browse...** to pick the `.shp` file.
   - **Loaded layer**: pick a polygon layer already loaded in the current
     QGIS project from the layer dropdown; the option is disabled if the
     project has no polygon layers. Loaded-layer input is exported to a
     temporary shapefile and automatically reprojected to EPSG:4326 on
     export, so the CRS warning below never applies to this path.

   Ideally the shapefile/layer has an attribute field named exactly
   `fcst_cat` (the forecast category code) -- if it does, nothing further
   is needed. If it doesn't, a **Forecast category field** dropdown
   appears listing the available attribute columns and you must pick one
   before **Upload** is enabled; the chosen column name is sent to the
   backend as `forecast_category_code_column`.

   Then choose the **Forecast period**, enter a **Forecast lead name**,
   confirm/adjust **Date produced** and **Year**, and leave **Cleanup**
   checked unless you specifically want to keep prior rows for the same
   period/year.
4. Click **Upload**. Progress shows in the progress bar; the result
   (success or the backend's error message) appears as a QGIS message-bar
   notification. On success the shapefile picker is cleared so you can
   queue the next upload immediately.

## Repository layout

```
qgis-pugin/
├── README.md
├── .gitignore
└── acmad_tools/                          <- the installable plugin (zip this folder)
    ├── __init__.py                        classFactory() entry point
    ├── metadata.txt                       plugin metadata (name, version, ...)
    ├── acmad_tools_plugin.py              initGui()/unload(): shared toolbar/menu + tool registry
    ├── core/
    │   ├── __init__.py
    │   └── settings_manager.py            QSettings persistence wrapper (shared across tools)
    └── tools/
        ├── __init__.py
        └── forecast_ingest/                the first tool
            ├── __init__.py
            ├── tool.py                     ForecastIngestTool: QAction + dialog-opening logic
            ├── upload_dialog.py            main upload dialog logic
            ├── upload_dialog_base.ui       main dialog layout (Qt Designer XML)
            ├── settings_dialog.py          settings dialog logic (URL/token/test)
            ├── settings_dialog_base.ui     settings dialog layout (Qt Designer XML)
            ├── network_client.py           QNetworkAccessManager multipart HTTP client
            └── shapefile_utils.py          sidecar lookup, CRS check, zip helper
```

## Adding a new tool

The toolbox has no plugin framework -- just a lightweight registry
pattern. To add a new tool:

1. Create a new subpackage under `acmad_tools/tools/<your_tool_name>/`
   with its own `__init__.py` and a `tool.py` module.
2. In `tool.py`, define a class implementing this small, plain
   duck-typed interface (no ABC/base class required):

   - `__init__(self, iface)` -- store `iface`; no UI side effects yet.
   - `name` -- a short display string used for the QAction text/tooltip.
   - `icon(self)` -- return a `QIcon` (a built-in QGIS theme icon via
     `QgsApplication.getThemeIcon(...)` is fine until a custom icon
     exists -- see `forecast_ingest/tool.py` for the pattern).
   - `initGui(self, menu, toolbar)` -- create your tool's `QAction`(s),
     connect `triggered` to whatever opens your tool's dialog/behaviour,
     and add the action to the given shared `menu` (a Plugins-menu name
     string, passed straight to `iface.addPluginToMenu`) and `toolbar`
     (the shared `QToolBar` instance). Store the action(s) on `self` so
     `unload` can remove them.
   - `unload(self)` -- remove/delete whatever `initGui` added (via
     `iface.removePluginMenu`/`iface.removeToolBarIcon`, and close any
     open dialog).

3. Put any dialogs/`.ui` files/network or business logic your tool needs
   as sibling modules inside the same `tools/<your_tool_name>/`
   subpackage. Reuse `acmad_tools/core/settings_manager.py` for the
   backend base URL/API token rather than adding a new settings store,
   unless your tool genuinely needs different connection settings.
4. Register it in `acmad_tools/acmad_tools_plugin.py`: import your
   tool's class and append one line to the `self._tools` list in
   `AcmadToolsPlugin.__init__`. Nothing else in that file needs to
   change -- `initGui`/`unload` already loop over every registered tool.

## Known limitations / things to verify in a real QGIS install

This plugin was written without access to a running QGIS instance, so it
follows standard, well-established PyQGIS/PyQt5 patterns rather than
anything exotic -- but the following are worth a first smoke-test:

- The plugin now bundles the official ACMAD logo as `acmad_tools/icon.png`
  (reused from `DroughtAdvisory/icon/AcmadLogo.png` in the backend repo, so
  it stays consistent with the rest of the ACMAD stack). `metadata.txt`
  references it via `icon=icon.png` (shown in the Plugin Manager listing),
  and each tool's `tool.py` loads the same file via `QIcon(...)` for its
  toolbar/menu action, falling back to the built-in theme icon
  `mActionSharingExport.svg` only if the bundled file is ever missing or
  fails to load. Worth a first-install check that the logo actually
  renders crisply at toolbar size (source image is 103x95px).
- `.ui` files were hand-written as Qt Designer XML (not exported from
  Designer itself). They follow standard `uic.loadUiType` conventions, but
  opening them once in Qt Designer/QGIS is a good sanity check.
- The `menu` argument passed to each tool's `initGui`/`unload` is a
  Plugins-menu *name string* (matching the original plugin's use of
  `iface.addPluginToMenu`/`removePluginMenu`), not a `QMenu` object --
  worth confirming this still reads/behaves as expected after the
  restructure, since it is easy to mentally conflate with an actual
  `QMenu` handle.
