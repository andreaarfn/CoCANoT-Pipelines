#!/bin/sh
set -e

COCANOT_PREFIX="${PREFIX}"

BIN_DIR="${HOME}/.local/bin"
APPLICATIONS_DIR="${HOME}/.local/share/applications"

mkdir -p "${BIN_DIR}"
mkdir -p "${APPLICATIONS_DIR}"

# Imaging launcher
cat > "${BIN_DIR}/cocanot-imaging" <<EOF
#!/bin/sh

PREFIX="${COCANOT_PREFIX}"

export PATH="\${PREFIX}/bin:\${PATH}"
export PYTHONPATH="\${PREFIX}/app:\${PYTHONPATH:-}"
export FSLDIR="\${PREFIX}"

exec "\${PREFIX}/bin/python" \
    "\${PREFIX}/app/ImagingPipeline/dashboard.py"
EOF

chmod +x "${BIN_DIR}/cocanot-imaging"

# Electrophysiology launcher
cat > "${BIN_DIR}/cocanot-electrophysiology" <<EOF
#!/bin/sh

PREFIX="${COCANOT_PREFIX}"

export PATH="\${PREFIX}/bin:\${PATH}"
export PYTHONPATH="\${PREFIX}/app:\${PYTHONPATH:-}"

exec "\${PREFIX}/bin/python" \
    "\${PREFIX}/app/ElectrophysiologyPipeline/dashboard.py"
EOF

chmod +x "${BIN_DIR}/cocanot-electrophysiology"


# Imaging desktop entry
cat > "${APPLICATIONS_DIR}/cocanot-imaging.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=CoCANoT Imaging
Comment=CoCANoT Imaging Pipeline
Exec=${BIN_DIR}/cocanot-imaging
Terminal=false
Categories=Science;
EOF


# Electrophysiology desktop entry
cat > "${APPLICATIONS_DIR}/cocanot-electrophysiology.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=CoCANoT Electrophysiology
Comment=CoCANoT Electrophysiology Pipeline
Exec=${BIN_DIR}/cocanot-electrophysiology
Terminal=false
Categories=Science;
EOF

chmod +x "${APPLICATIONS_DIR}/cocanot-imaging.desktop"
chmod +x "${APPLICATIONS_DIR}/cocanot-electrophysiology.desktop"

exit 0