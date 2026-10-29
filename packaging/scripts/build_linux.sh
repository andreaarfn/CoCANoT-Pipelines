#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STAGE="$ROOT/packaging/stage-linux"
CONSTRUCT="$ROOT/packaging/constructor/linux"
case "$(uname -s)" in Linux) ;; *) echo "Build on Linux, not macOS." >&2; exit 1;; esac
ARCH="$(uname -m)"
case "$ARCH" in x86_64) SUBDIR=linux-64;; aarch64) echo "PyFaceWipe has no verified Linux ARM64 wheel; this build target is not yet supported." >&2; exit 1;; *) echo "Unsupported architecture: $ARCH" >&2; exit 1;; esac
: "${CONDA_PREFIX:?Activate an architecture-matching Conda build environment first}"
test "$("$CONDA_PREFIX/bin/python" -c 'import platform; print(platform.machine())')" = "$ARCH"
command -v constructor >/dev/null || { echo "Install conda constructor in build environment." >&2; exit 1; }
command -v npm >/dev/null || { echo "Install Node.js/npm on the Linux build machine." >&2; exit 1; }
cd "$ROOT/react_frontend"
npm ci
npm run build
test -f dist/index.html
rm -rf "$STAGE"
mkdir -p "$STAGE/payload" "$STAGE/pip_packages"
cp "$ROOT/react_dashboard.py" "$ROOT/pipeline_config.py" "$STAGE/payload/"
cp "$ROOT/packaging/environment/requirements-pip-linux.txt" "$STAGE/payload/packaging_requirements_pip.txt"
mkdir -p "$STAGE/payload/react_frontend"
cp -R "$ROOT/react_frontend/dist" "$STAGE/payload/react_frontend/"
for component in app config MetadataPipeline; do cp -R "$ROOT/$component" "$STAGE/payload/"; done
for component in ImagingPipeline ElectrophysiologyPipeline; do
  mkdir -p "$STAGE/payload/$component"
  cp -R "$ROOT/$component/scripts" "$STAGE/payload/$component/"
done
find "$STAGE/payload" -name __pycache__ -type d -prune -exec rm -rf {} +
find "$STAGE/payload" -name '*.pyc' -delete
find "$STAGE/payload" -name '.DS_Store' -delete
tar -czf "$STAGE/app_payload.tar.gz" -C "$STAGE/payload" .
"$CONDA_PREFIX/bin/python" -m pip wheel --wheel-dir "$STAGE/pip_packages" --no-deps 'proxy-tools==0.1.0'
grep -v -E '^(proxy-tools==|pyfacewipe([[:space:]]|$))' "$ROOT/packaging/environment/requirements-pip-linux.txt" > "$STAGE/requirements-binary.txt"
"$CONDA_PREFIX/bin/python" -m pip download --dest "$STAGE/pip_packages" --only-binary=:all: --no-deps -r "$STAGE/requirements-binary.txt"
"$CONDA_PREFIX/bin/python" -m pip download --dest "$STAGE/pip_packages" --only-binary=:all: --no-deps "https://github.com/olinickalls/PyFaceWipe/releases/download/v0.1.3/pyfacewipe-0.1.3-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.manylinux_2_28_x86_64.whl"
"$CONDA_PREFIX/bin/python" -m pip download --dest "$STAGE/pip_packages" --only-binary=:all: medio scipy scikit-image pylibjpeg pylibjpeg-libjpeg xxhash numpy nibabel Pillow
# Bundle CPU-only Torch rather than the large default Linux CUDA distribution.
"$CONDA_PREFIX/bin/python" -m pip download --dest "$STAGE/pip_packages" --only-binary=:all: torch --index-url https://download.pytorch.org/whl/cpu
tar -czf "$STAGE/pip_packages.tar.gz" -C "$STAGE/pip_packages" .
export CONDA_PKGS_DIRS="$STAGE/conda-cache"
mkdir -p "$CONDA_PKGS_DIRS"
cd "$CONSTRUCT"
constructor .
test -f CoCANoT-Linux.sh
mv -f CoCANoT-Linux.sh "CoCANoT-Linux-$ARCH.sh"
echo "Built $CONSTRUCT/CoCANoT-Linux-$ARCH.sh for $SUBDIR"
