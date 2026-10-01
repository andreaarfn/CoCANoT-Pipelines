#!/bin/bash
set -euo pipefail

PREFIX="${1:-/Library/CoCANoT-Pipelines}"

echo "Verifying CoCANoT installation at ${PREFIX}"

checks=(
  "${PREFIX}/bin/python"
  "${PREFIX}/bin/dcm2niix"
  "${PREFIX}/bin/flirt"
  "${PREFIX}/bin/pydeface"
  "${PREFIX}/app/react_dashboard.py"
  "${PREFIX}/app/react_frontend/dist/index.html"
  "${PREFIX}/app/MetadataPipeline/dictionaries/CoCANoT_Metadata_Phase1.0.xlsx"
  "/Applications/CoCANoT.app/Contents/MacOS/launch"
  "/Applications/Uninstall CoCANoT.app/Contents/MacOS/launch"
)

failed=0
for item in "${checks[@]}"; do
    if [ -e "${item}" ]; then
        echo "OK: ${item}"
    else
        echo "MISSING: ${item}"
        failed=1
    fi
done

if [ "${failed}" -ne 0 ]; then
    exit 1
fi

"${PREFIX}/bin/python" - <<'PY'
import webview, fitz, PIL, nibabel, numpy, matplotlib, openpyxl, pyedflib
print("Python imports: OK")
PY

echo "CoCANoT installation verification passed."
