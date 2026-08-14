# ACMAD Forecast Ingest -- QGIS plugin

A QGIS 3.x plugin that lets a domain expert upload a drought forecast
polygon shapefile directly from QGIS to the ACMAD Drought Advisory
backend's REST API, instead of a manual out-of-band upload process.

The plugin code lives in the [`acmad_forecast_ingest/`](./acmad_forecast_ingest)
directory -- that directory *is* the installable QGIS plugin.

## What it does

1. You pick a `.shp` file from disk (its `.shx`/`.dbf`/`.prj`/`.cpg`
   sidecar files must be alongside it).
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

If the shapefile's `.prj` CRS is not `EPSG:4326` (WGS84), the plugin shows
a non-blocking warning but still allows the upload -- it does **not**
reproject. Reprojection, exporting directly from a loaded layer, and any
kind of self-service login/token-issuing flow are explicitly out of scope
for this first version.

## Installation

1. Zip the `acmad_forecast_ingest/` folder itself (the zip's top-level
   entry must be the `acmad_forecast_ingest` directory -- e.g. from this
   repo root: `cd acmad_forecast_ingest && zip -r ../acmad_forecast_ingest.zip . -x '.*'`,
   or just zip the folder in Finder/Explorer).
2. In QGIS: **Plugins -> Manage and Install Plugins... -> Install from
   ZIP**, select the zip file, click **Install Plugin**.
3. Enable the plugin if it isn't auto-enabled (**Plugins -> Manage and
   Install Plugins... -> Installed**, check "ACMAD Forecast Ingest").
4. A toolbar icon and a **Plugins -> ACMAD Forecast Ingest** menu entry
   ("Upload Forecast to ACMAD...") appear.

## Getting an API token

There is no self-service sign-up. A backend administrator issues you a
token out-of-band (Django admin, or the management command below run on
the server):

```
python manage.py default_api_token_generation <username>
```

Paste that token into the plugin's Settings dialog (see below) -- it is
stored locally via QGIS's `QSettings` (organisation `ACMAD`, application
`ForecastIngestPlugin`) and reused for every upload.

## Using the plugin

1. Click the toolbar icon (or **Plugins -> ACMAD Forecast Ingest ->
   Upload Forecast to ACMAD...**).
2. Click **Settings...** (first time only, or whenever the server URL /
   token changes): enter the server base URL (e.g.
   `https://acmad-drought.example.org`, no trailing slash needed) and the
   API token, then click **Test Connection** to confirm both the URL and
   the token are correct before saving.
3. Back in the main dialog: **Browse...** to pick the `.shp` file, choose
   the **Forecast period**, enter a **Forecast lead name**, confirm/adjust
   **Date produced** and **Year**, and leave **Cleanup** checked unless you
   specifically want to keep prior rows for the same period/year.
4. Click **Upload**. Progress shows in the progress bar; the result
   (success or the backend's error message) appears as a QGIS message-bar
   notification. On success the shapefile picker is cleared so you can
   queue the next upload immediately.

## Repository layout

```
qgis-pugin/
├── README.md
├── .gitignore
└── acmad_forecast_ingest/        <- the installable plugin (zip this folder)
    ├── __init__.py                classFactory() entry point
    ├── metadata.txt                plugin metadata (name, version, ...)
    ├── acmad_forecast_ingest.py    initGui()/unload()/toolbar+menu wiring
    ├── upload_dialog.py            main upload dialog logic
    ├── upload_dialog_base.ui       main dialog layout (Qt Designer XML)
    ├── settings_dialog.py          settings dialog logic (URL/token/test)
    ├── settings_dialog_base.ui     settings dialog layout (Qt Designer XML)
    ├── network_client.py           QNetworkAccessManager multipart HTTP client
    ├── settings_manager.py         QSettings persistence wrapper
    └── shapefile_utils.py          sidecar lookup, CRS check, zip helper
```

## Known limitations / things to verify in a real QGIS install

This plugin was written without access to a running QGIS instance, so it
follows standard, well-established PyQGIS/PyQt5 patterns rather than
anything exotic -- but the following are worth a first smoke-test:

- The toolbar/menu icon falls back to the built-in theme icon
  `mActionSharingExport.svg` (`QgsApplication.getThemeIcon(...)`) since no
  custom `icon.png` ships yet. If that theme icon name doesn't resolve on
  your QGIS version, `getThemeIcon` degrades gracefully to a null icon
  (blank, but the plugin still works) rather than raising -- swap in a
  real `icon.png` when one exists.
- `.ui` files were hand-written as Qt Designer XML (not exported from
  Designer itself). They follow standard `uic.loadUiType` conventions, but
  opening them once in Qt Designer/QGIS is a good sanity check.
