# -*- coding: utf-8 -*-
"""Shapefile helpers: sibling-file discovery, CRS sanity check, zipping.

Kept free of any Qt *widget* imports (only ``qgis.core`` for CRS parsing)
so it can be unit-tested or reused outside of a dialog context.
"""

import os
import tempfile
import zipfile
from typing import Dict, List, Optional, Tuple

# .shx/.dbf/.prj are mandatory companions of a .shp for it to be a valid,
# loadable shapefile; .cpg (codepage) is optional but included when present
# since it affects attribute-string decoding on the server side.
REQUIRED_SIDECAR_EXTENSIONS = [".shx", ".dbf", ".prj"]
OPTIONAL_SIDECAR_EXTENSIONS = [".cpg"]
ALL_SIDECAR_EXTENSIONS = REQUIRED_SIDECAR_EXTENSIONS + OPTIONAL_SIDECAR_EXTENSIONS

TARGET_AUTHID = "EPSG:4326"


def get_shapefile_parts(shp_path: str) -> Dict[str, str]:
    """Return {extension: path} for the .shp plus any sidecar files found.

    Sidecar files are looked up case-sensitively first (the common case on
    Linux/macOS) and, if missing, in upper- and mixed-case common variants
    (some shapefile producers, notably older Windows GIS tools, emit
    upper-case extensions).
    """
    base, _ = os.path.splitext(shp_path)
    directory = os.path.dirname(shp_path) or "."
    parts: Dict[str, str] = {}

    if os.path.isfile(shp_path):
        parts[".shp"] = shp_path

    for ext in ALL_SIDECAR_EXTENSIONS:
        candidates = [base + ext, base + ext.upper()]
        for candidate in candidates:
            if os.path.isfile(candidate):
                parts[ext] = candidate
                break
        else:
            # Fall back to a case-insensitive directory scan, in case the
            # base name itself differs only in case from the .shp (rare,
            # but cheap to guard against).
            base_name_lower = os.path.basename(base).lower()
            try:
                for entry in os.listdir(directory):
                    entry_base, entry_ext = os.path.splitext(entry)
                    if (
                        entry_base.lower() == base_name_lower
                        and entry_ext.lower() == ext
                    ):
                        parts[ext] = os.path.join(directory, entry)
                        break
            except OSError:
                pass

    return parts


def validate_shapefile_complete(shp_path: str) -> Tuple[bool, List[str]]:
    """Check that a .shp and all its required sidecar files exist.

    Returns:
        (is_complete, missing_extensions) -- missing_extensions is empty
        when is_complete is True.
    """
    if not shp_path or not os.path.isfile(shp_path):
        return False, [".shp (file not found)"]

    parts = get_shapefile_parts(shp_path)
    missing = [ext for ext in REQUIRED_SIDECAR_EXTENSIONS if ext not in parts]
    return (len(missing) == 0, missing)


def check_crs_is_wgs84(prj_path: Optional[str]) -> Tuple[bool, Optional[str], Optional[str]]:
    """Parse a .prj file's WKT and check whether it is EPSG:4326.

    Returns:
        (is_wgs84, authid, error_message). ``authid`` is None if the CRS
        could not be determined; ``error_message`` is None on success.
    """
    if not prj_path or not os.path.isfile(prj_path):
        return False, None, "No .prj file found alongside the shapefile."

    try:
        with open(prj_path, "r", encoding="utf-8", errors="replace") as handle:
            wkt = handle.read().strip()
    except OSError as exc:
        return False, None, f"Could not read .prj file: {exc}"

    if not wkt:
        return False, None, "The .prj file is empty."

    # Imported lazily: this module is otherwise Qt/QGIS-free so it stays
    # easy to reason about, and importing qgis.core is only meaningful
    # once a QGIS/QApplication environment actually exists.
    from qgis.core import QgsCoordinateReferenceSystem

    crs = QgsCoordinateReferenceSystem()
    crs.createFromWkt(wkt)

    if not crs.isValid():
        return False, None, "Could not determine a valid CRS from the .prj file."

    authid = crs.authid()  # e.g. "EPSG:4326", or "" if QGIS cannot match one
    is_wgs84 = authid.upper() == TARGET_AUTHID
    return is_wgs84, (authid or None), None


def get_shapefile_field_names(shp_path: str) -> List[str]:
    """Return the attribute field names of a shapefile on disk.

    Opens the shapefile via the OGR provider purely to read its field
    schema -- the QgsVectorLayer created here is never added to the
    project/canvas, just built, inspected, and left to be garbage
    collected. Used to detect whether a `fcst_cat` field is present
    before falling back to letting the user pick a column themselves.

    Returns:
        Field names in layer order, or [] if the file can't be opened as
        a valid vector layer (missing sidecars, corrupt file, etc.) --
        callers treat an empty list as "couldn't introspect", not as "a
        shapefile with zero fields".
    """
    # Imported lazily, same rationale as check_crs_is_wgs84 above: keeps
    # this module importable without a QGIS/QApplication environment.
    from qgis.core import QgsVectorLayer

    layer = QgsVectorLayer(shp_path, "field_probe", "ogr")
    if not layer.isValid():
        return []
    return [field.name() for field in layer.fields()]


def zip_shapefile(shp_path: str, dest_dir: Optional[str] = None) -> Tuple[str, str]:
    """Zip the .shp and its sidecar files into a single archive.

    Args:
        shp_path: Path to the .shp file.
        dest_dir: Directory to write the zip into. If None, a fresh
            temporary directory is created (caller is responsible for
            removing it -- see NetworkClient's cleanup-after-request logic).

    Returns:
        (zip_path, dest_dir) -- dest_dir is returned so the caller can
        clean up the whole temp directory later, even if it was
        auto-created here.
    """
    parts = get_shapefile_parts(shp_path)
    if ".shp" not in parts:
        raise FileNotFoundError(f"Shapefile not found: {shp_path}")

    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix="acmad_forecast_ingest_")

    base_name = os.path.splitext(os.path.basename(shp_path))[0]
    zip_path = os.path.join(dest_dir, f"{base_name}.zip")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for ext, part_path in parts.items():
            # Store files flat (no directory structure) with their
            # original extension -- this matches what the backend's
            # _safe_extract_zip / _find_shapefile expects (a flat set of
            # same-basename shapefile parts, found anywhere under the
            # extracted tree).
            archive.write(part_path, arcname=os.path.basename(part_path))

    return zip_path, dest_dir
