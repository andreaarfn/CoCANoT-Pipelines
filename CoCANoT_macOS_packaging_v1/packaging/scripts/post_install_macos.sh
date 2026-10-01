#!/bin/bash
set -euo pipefail

COCANOT_PREFIX="${PREFIX}"
APPLICATIONS_DIR="/Applications"
PAYLOAD_ARCHIVE="${COCANOT_PREFIX}/payload/app_payload.tar.gz"
ICON_SOURCE="${COCANOT_PREFIX}/payload/logo.icns"
UNINSTALL_SOURCE="${COCANOT_PREFIX}/payload/uninstall_macos.sh"
APP_DIR="${COCANOT_PREFIX}/app"

echo "Configuring CoCANoT..."

if [ ! -x "${COCANOT_PREFIX}/bin/python" ]; then
    echo "ERROR: bundled Python runtime is missing."
    exit 1
fi

for TOOL in dcm2niix flirt pydeface; do
    if [ ! -x "${COCANOT_PREFIX}/bin/${TOOL}" ]; then
        echo "ERROR: bundled dependency is missing: ${TOOL}"
        exit 1
    fi
done

if [ ! -f "${PAYLOAD_ARCHIVE}" ]; then
    echo "ERROR: CoCANoT application payload is missing."
    exit 1
fi

rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}"
/usr/bin/tar -xzf "${PAYLOAD_ARCHIVE}" -C "${APP_DIR}"

if [ ! -f "${APP_DIR}/react_dashboard.py" ]; then
    echo "ERROR: react_dashboard.py was not installed."
    exit 1
fi

if [ ! -f "${APP_DIR}/react_frontend/dist/index.html" ]; then
    echo "ERROR: bundled React build was not installed."
    exit 1
fi

if [ ! -f "${APP_DIR}/MetadataPipeline/dictionaries/CoCANoT_Metadata_Phase1.0.xlsx" ]; then
    echo "ERROR: machine-readable metadata dictionary was not installed."
    exit 1
fi

chmod +x "${UNINSTALL_SOURCE}"

create_main_app() {
    APP_PATH="${APPLICATIONS_DIR}/CoCANoT.app"
    rm -rf "${APP_PATH}"
    mkdir -p "${APP_PATH}/Contents/MacOS" "${APP_PATH}/Contents/Resources"
    cp "${ICON_SOURCE}" "${APP_PATH}/Contents/Resources/logo.icns"

    cat > "${APP_PATH}/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>CoCANoT</string>
  <key>CFBundleDisplayName</key>
  <string>CoCANoT</string>
  <key>CFBundleIdentifier</key>
  <string>org.cocanot.app</string>
  <key>CFBundleVersion</key>
  <string>0.2.0</string>
  <key>CFBundleShortVersionString</key>
  <string>0.2.0</string>
  <key>CFBundleExecutable</key>
  <string>launch</string>
  <key>CFBundleIconFile</key>
  <string>logo.icns</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
EOF

    cat > "${APP_PATH}/Contents/MacOS/launch" <<EOF
#!/bin/bash
set -e

PREFIX="${COCANOT_PREFIX}"
APP_ROOT="\${PREFIX}/app"

# Force CoCANoT to use only its bundled runtime/dependencies.
export PATH="\${PREFIX}/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONPATH="\${APP_ROOT}"
export PYTHONNOUSERSITE=1
export FSLDIR="\${PREFIX}"

cd "\${APP_ROOT}"

exec "\${PREFIX}/bin/python" "\${APP_ROOT}/react_dashboard.py"
EOF

    chmod +x "${APP_PATH}/Contents/MacOS/launch"
}

create_uninstaller_app() {
    APP_PATH="${APPLICATIONS_DIR}/Uninstall CoCANoT.app"
    rm -rf "${APP_PATH}"
    mkdir -p "${APP_PATH}/Contents/MacOS" "${APP_PATH}/Contents/Resources"
    cp "${ICON_SOURCE}" "${APP_PATH}/Contents/Resources/logo.icns"

    cat > "${APP_PATH}/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Uninstall CoCANoT</string>
  <key>CFBundleDisplayName</key>
  <string>Uninstall CoCANoT</string>
  <key>CFBundleIdentifier</key>
  <string>org.cocanot.uninstaller</string>
  <key>CFBundleVersion</key>
  <string>0.2.0</string>
  <key>CFBundleShortVersionString</key>
  <string>0.2.0</string>
  <key>CFBundleExecutable</key>
  <string>launch</string>
  <key>CFBundleIconFile</key>
  <string>logo.icns</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
EOF

    cat > "${APP_PATH}/Contents/MacOS/launch" <<EOF
#!/bin/bash
set -e

COCANOT_PREFIX="${COCANOT_PREFIX}"
UNINSTALL_SCRIPT="\${COCANOT_PREFIX}/payload/uninstall_macos.sh"

RESULT=\$(/usr/bin/osascript <<'APPLESCRIPT'
try
    display dialog "Uninstall CoCANoT completely?

This removes the CoCANoT application, its private Python/runtime dependencies, local CoCANoT database and settings, caches, logs, preferences, and installer receipts.

It will NOT delete source DICOM/NIfTI/EDF data or user-selected derivatives/BIDS output folders." buttons {"Cancel", "Uninstall Everything"} default button "Uninstall Everything" cancel button "Cancel" with title "Uninstall CoCANoT"
    return button returned of result
on error number -128
    return "Cancel"
end try
APPLESCRIPT
)

if [ "\${RESULT}" != "Uninstall Everything" ]; then
    exit 0
fi

if [ ! -f "\${UNINSTALL_SCRIPT}" ]; then
    /usr/bin/osascript <<'APPLESCRIPT'
display dialog "The CoCANoT uninstall script could not be found." buttons {"OK"} default button "OK" with icon caution with title "CoCANoT Uninstaller"
APPLESCRIPT
    exit 1
fi

TEMP_SCRIPT=\$(mktemp "/tmp/cocanot-uninstall.XXXXXX")
cp "\${UNINSTALL_SCRIPT}" "\${TEMP_SCRIPT}"
chmod 700 "\${TEMP_SCRIPT}"

/usr/bin/osascript <<APPLESCRIPT
do shell script "/bin/bash " & quoted form of "\${TEMP_SCRIPT}" & " --yes --prefix " & quoted form of "\${COCANOT_PREFIX}" with administrator privileges
APPLESCRIPT

STATUS=\$?
rm -f "\${TEMP_SCRIPT}" 2>/dev/null || true

if [ "\${STATUS}" -eq 0 ]; then
    /usr/bin/osascript <<'APPLESCRIPT'
display dialog "CoCANoT was removed successfully." buttons {"OK"} default button "OK" with title "CoCANoT Uninstaller"
APPLESCRIPT
else
    /usr/bin/osascript <<'APPLESCRIPT'
display dialog "CoCANoT could not be completely removed. Please contact the CoCANoT development team." buttons {"OK"} default button "OK" with icon caution with title "CoCANoT Uninstaller"
APPLESCRIPT
fi
EOF

    chmod +x "${APP_PATH}/Contents/MacOS/launch"
}

create_main_app
create_uninstaller_app

# Remove compressed application payload after expansion. The private runtime
# and source under ${COCANOT_PREFIX}/app remain installed.
rm -f "${PAYLOAD_ARCHIVE}"

echo "CoCANoT post-install setup completed."
