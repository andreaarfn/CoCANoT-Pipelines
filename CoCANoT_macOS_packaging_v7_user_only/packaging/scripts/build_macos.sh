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
cp "${PACKAGING_DIR}/environment/requirements-pip-bundled.txt" "${PAYLOAD_ROOT}/packaging_requirements_pip.txt"

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
# 4. Bundle exact pip-installed dependencies for offline install.
#
# Constructor packages conda packages, but packages that exist only as
# pip-installed files in the developer environment are not automatically
# carried into the target environment. Download those exact distributions
# now so the recipient never needs internet, Homebrew, or a personal Python.
# ------------------------------------------------------------
PIP_REQ="${PACKAGING_DIR}/environment/requirements-pip-bundled.txt"
PIP_STAGE="${STAGE_DIR}/pip_packages"
PIP_ARCHIVE="${STAGE_DIR}/pip_packages.tar.gz"
PIP_BINARY_REQ="${STAGE_DIR}/requirements-pip-binary.txt"

rm -rf "${PIP_STAGE}"
mkdir -p "${PIP_STAGE}"

# proxy-tools 0.1.0 is published as source, but pywebview imports it at runtime.
# Build its wheel NOW on the developer machine, where build dependencies and
# internet access are available. Recipient Macs never build Python packages.
"${CONDA_PREFIX}/bin/python" -m pip wheel \
  --wheel-dir "${PIP_STAGE}" \
  --no-deps \
  "proxy-tools==0.1.0"

# All remaining pip dependencies must already have binary wheels. If a future
# package lacks one, fail the BUILD here instead of failing on a clinical site.
grep -v '^proxy-tools==' "${PIP_REQ}" > "${PIP_BINARY_REQ}"

"${CONDA_PREFIX}/bin/python" -m pip download \
  --dest "${PIP_STAGE}" \
  --no-deps \
  --only-binary=:all: \
  --requirement "${PIP_BINARY_REQ}"

# Confirm the required runtime packages are actually present in the bundle.
ls "${PIP_STAGE}"/proxy_tools-0.1.0-*.whl >/dev/null 2>&1 || {
  echo "ERROR: proxy-tools wheel was not built."
  exit 1
}
ls "${PIP_STAGE}"/pywebview-6.2.1-*.whl >/dev/null 2>&1 || {
  echo "ERROR: pywebview wheel was not downloaded."
  exit 1
}
ls "${PIP_STAGE}"/pydeface-2.1.0-*.whl >/dev/null 2>&1 || {
  echo "ERROR: pydeface wheel was not downloaded."
  exit 1
}

cd "${PIP_STAGE}"
/usr/bin/tar -czf "${PIP_ARCHIVE}" .

# ------------------------------------------------------------
# 5. Build the self-contained macOS installer.
# ------------------------------------------------------------
cd "${CONSTRUCT_DIR}"

# Constructor's default cache is ~/.conda/constructor. That directory can
# become root-owned after package testing with sudo, which causes:
#   NoWritablePkgsDirError: ~/.conda/constructor/osx-arm64
#
# Keep all Constructor/Conda build caches inside the project instead.
CONSTRUCTOR_CACHE="${STAGE_DIR}/constructor_cache"
CONDA_PKGS_CACHE="${STAGE_DIR}/conda_pkgs"

rm -rf "${CONSTRUCTOR_CACHE}" "${CONDA_PKGS_CACHE}"
mkdir -p "${CONSTRUCTOR_CACHE}" "${CONDA_PKGS_CACHE}"

export CONDA_PKGS_DIRS="${CONDA_PKGS_CACHE}"

constructor   --cache-dir "${CONSTRUCTOR_CACHE}"   .

echo ""
echo "Build complete."
echo "Installer output is in: ${CONSTRUCT_DIR}"
