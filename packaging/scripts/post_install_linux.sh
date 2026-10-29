#!/usr/bin/env bash
set -euo pipefail
PREFIX="${PREFIX:?Constructor PREFIX must be provided}"
case "$PREFIX" in
  "$HOME"/.local/share/CoCANoT/runtime) ;;
  *) echo "Refusing unexpected install prefix: $PREFIX" >&2; exit 1 ;;
esac
ROOT="$PREFIX/app"
mkdir -p "$ROOT" "$HOME/.local/share/applications" "$HOME/.local/bin"
tar -xzf "$PREFIX/payload/app_payload.tar.gz" -C "$ROOT"
mkdir -p "$PREFIX/payload/pip_packages"
tar -xzf "$PREFIX/payload/pip_packages.tar.gz" -C "$PREFIX/payload/pip_packages"
"$PREFIX/bin/python" -m pip install --no-index --only-binary=:all: \
  --find-links "$PREFIX/payload/pip_packages" \
  -r "$ROOT/packaging_requirements_pip.txt"
"$PREFIX/bin/python" - <<'PY'
import webview, numpy, nibabel, pyedflib, fitz, openpyxl, pyfacewipe, torch
print("CoCANoT Python dependency imports OK")
PY
test -f "$ROOT/react_frontend/dist/index.html"
test -f "$ROOT/MetadataPipeline/dictionaries/CoCANoT_Metadata_Phase1.0.xlsx"
cat > "$HOME/.local/bin/cocanot" <<EOF
#!/usr/bin/env bash
set -e
export PATH="$PREFIX/bin:\$PATH"
export PYTHONNOUSERSITE=1
export PYTHONPATH="$ROOT"
cd "$ROOT"
exec "$PREFIX/bin/python" "$ROOT/react_dashboard.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/cocanot"
cat > "$HOME/.local/share/applications/org.cocanot.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=CoCANoT
Comment=CoCANoT De-identification and Validation
Exec=$HOME/.local/bin/cocanot
Terminal=false
Categories=Science;Education;
EOF
echo "CoCANoT installed: $HOME/.local/bin/cocanot"
echo "Linux GUI requires a desktop with GTK 3 and WebKit2GTK 4.1 or a compatible pywebview backend."
