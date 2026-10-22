#!/usr/bin/env bash
set -euo pipefail
PREFIX="${1:-$HOME/.local/share/CoCANoT/runtime}"
test -x "$PREFIX/bin/python"
test -x "$PREFIX/bin/dcm2niix"
test -x "$PREFIX/bin/flirt"
test -f "$PREFIX/app/react_frontend/dist/index.html"
test -f "$PREFIX/app/MetadataPipeline/dictionaries/CoCANoT_Metadata_Phase1.0.xlsx"
test -x "$HOME/.local/bin/cocanot"
"$PREFIX/bin/python" - <<'PY'
import webview, fitz, PIL, nibabel, numpy, matplotlib, openpyxl, pyedflib
print("CoCANoT Linux bundled imports OK")
PY
echo "Linux installation passed file and import checks."
