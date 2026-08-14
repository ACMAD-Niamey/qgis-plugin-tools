#!/usr/bin/env bash
# Packages the acmad_tools/ plugin directory into an installable QGIS zip.
#
# This is the single source of truth for building a release zip -- both the
# CI/release GitHub Actions workflows and any human doing a manual release
# should call this script rather than re-implementing the zip logic, so the
# packaging behaviour (exclusions, top-level folder name, version parsing)
# never drifts between "what CI ships" and "what a developer tests locally".
#
# Usage:
#   scripts/package.sh          # build dist/acmad_tools-<version>.zip
#   scripts/package.sh --version  # print just the version from metadata.txt and exit
set -euo pipefail

# Resolve paths relative to this script's own location so it can be run from
# any working directory, not just the repo root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PLUGIN_DIR="${REPO_ROOT}/acmad_tools"
METADATA_FILE="${PLUGIN_DIR}/metadata.txt"
DIST_DIR="${REPO_ROOT}/dist"

if [[ ! -f "${METADATA_FILE}" ]]; then
    echo "error: metadata file not found at ${METADATA_FILE}" >&2
    exit 1
fi

# Simple grep/sed extraction of the version= line -- metadata.txt is a small,
# well-known INI file so a full parser would be overkill.
VERSION="$(grep -E '^version=' "${METADATA_FILE}" | head -n1 | sed -E 's/^version=//')"

if [[ -z "${VERSION}" ]]; then
    echo "error: could not find a version= line in ${METADATA_FILE}" >&2
    exit 1
fi

# Allow callers (e.g. the release workflow) to just query the version without
# building a zip, so version-parsing logic lives in exactly one place.
if [[ "${1:-}" == "--version" ]]; then
    echo "${VERSION}"
    exit 0
fi

ZIP_NAME="acmad_tools-${VERSION}.zip"
ZIP_PATH="${DIST_DIR}/${ZIP_NAME}"

mkdir -p "${DIST_DIR}"

# Clear any pre-existing zip of the same name first so stale contents never
# leak into a "fresh" build.
rm -f "${ZIP_PATH}"

# Zip from inside acmad_tools/'s parent so the top-level entry inside the
# archive is the "acmad_tools/" directory itself -- QGIS's "Install from
# ZIP" uses that folder name as the Python module name, so this layout is
# required for the plugin to install correctly.
#
# Exclusions mirror the repo's .gitignore: __pycache__/, compiled .pyc
# files, and .DS_Store.
(
    cd "${REPO_ROOT}"
    zip -r -q "${ZIP_PATH}" acmad_tools \
        -x '*/__pycache__/*' \
        -x '*.pyc' \
        -x '*.DS_Store'
)

echo "${ZIP_PATH}"
