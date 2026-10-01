#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PACKAGING_DIR="${PROJECT_ROOT}/packaging"
STAGE_DIR="${PACKAGING_DIR}/stage"
PAYLOAD_ROOT="${STAGE_DIR}/payload"
PAYLOAD_ARCHIVE="${STAGE_DIR}/app_payload.tar.gz"
CONSTRUCT_DIR="${PACKAGING_DIR}/constructor/macos"

echo "Project root: ${PROJECT_ROOT}"

# ------------------------------------------------------------
# 1. Build React on the developer/build machine only.
# ------------------------------------------------------------
cd "${PROJECT_ROOT}/react_frontend"

if [ -f package-lock.json ]; then
    npm ci
else
    npm install
fi

npm run build

test -f "${PROJECT_ROOT}/react_frontend/dist/index.html"

# ------------------------------------------------------------
# 2. Create a clean runtime payload.
# ------------------------------------------------------------
rm -rf "${STAGE_DIR}"
mkdir -p "${PAYLOAD_ROOT}"

cp "${PROJECT_ROOT}/react_dashboard.py" "${PAYLOAD_ROOT}/"
cp "${PROJECT_ROOT}/pipeline_config.py" "${PAYLOAD_ROOT}/"

mkdir -p "${PAYLOAD_ROOT}/react_frontend"
cp -R "${PROJECT_ROOT}/react_frontend/dist" "${PAYLOAD_ROOT}/react_frontend/dist"

cp -R "${PROJECT_ROOT}/app" "${PAYLOAD_ROOT}/app"
cp -R "${PROJECT_ROOT}/config" "${PAYLOAD_ROOT}/config"

mkdir -p "${PAYLOAD_ROOT}/ImagingPipeline"
cp -R "${PROJECT_ROOT}/ImagingPipeline/scripts" "${PAYLOAD_ROOT}/ImagingPipeline/scripts"

mkdir -p "${PAYLOAD_ROOT}/ElectrophysiologyPipeline"
cp -R "${PROJECT_ROOT}/ElectrophysiologyPipeline/scripts" "${PAYLOAD_ROOT}/ElectrophysiologyPipeline/scripts"

cp -R "${PROJECT_ROOT}/MetadataPipeline" "${PAYLOAD_ROOT}/MetadataPipeline"

# Remove files that are development-only or can accidentally be copied from
# an editor/build machine.
find "${PAYLOAD_ROOT}" -name '.DS_Store' -delete
find "${PAYLOAD_ROOT}" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "${PAYLOAD_ROOT}" -name '*.pyc' -delete
find "${PAYLOAD_ROOT}" -name '.pytest_cache' -type d -prune -exec rm -rf {} +
find "${PAYLOAD_ROOT}/MetadataPipeline" -name 'tests' -type d -prune -exec rm -rf {} +
find "${PAYLOAD_ROOT}/MetadataPipeline/dictionaries" -name '~$*' -delete

# Old standalone/Tkinter launchers are not part of the distributed app.
rm -f "${PAYLOAD_ROOT}/MetadataPipeline/dashboard.py" \
      "${PAYLOAD_ROOT}/MetadataPipeline/dashboard.py.before_single_window" \
      "${PAYLOAD_ROOT}/MetadataPipeline/customtkinter_dashboard.py" 2>/dev/null || true

# Ensure runtime settings start empty and are created under ~/.cocanot.
rm -f "${PAYLOAD_ROOT}/pipeline_settings.json"

# ------------------------------------------------------------
# 3. Archive the app payload for Constructor.
# ------------------------------------------------------------
cd "${PAYLOAD_ROOT}"
/usr/bin/tar -czf "${PAYLOAD_ARCHIVE}" .

# ------------------------------------------------------------
# 4. Build the self-contained macOS installer.
# ------------------------------------------------------------
cd "${CONSTRUCT_DIR}"
constructor .

echo ""
echo "Build complete."
echo "Installer output is in: ${CONSTRUCT_DIR}"
