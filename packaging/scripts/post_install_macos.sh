#!/bin/bash

set -e

# ============================================================
# CoCANoT Pipelines macOS post-install setup
# ============================================================

COCANOT_PREFIX="${PREFIX}"
APPLICATIONS_DIR="/Applications"

ICON_SOURCE="${COCANOT_PREFIX}/app/assets/logo.icns"
UNINSTALL_SCRIPT_SOURCE="${COCANOT_PREFIX}/app/uninstall_macos.sh"


# ============================================================
# Install and verify PyDeface
# ============================================================

echo ""
echo "Installing PyDeface into the CoCANoT environment..."

if [ ! -x "${COCANOT_PREFIX}/bin/python" ]; then
    echo "ERROR: CoCANoT Python runtime was not found:"
    echo "${COCANOT_PREFIX}/bin/python"
    exit 1
fi

"${COCANOT_PREFIX}/bin/python" \
    -m pip install \
    --no-input \
    --disable-pip-version-check \
    pydeface==2.1.0

if [ ! -x "${COCANOT_PREFIX}/bin/pydeface" ]; then
    echo "ERROR: PyDeface was not installed correctly."
    echo "Expected executable:"
    echo "${COCANOT_PREFIX}/bin/pydeface"
    exit 1
fi

echo "PyDeface installation verified."


# ============================================================
# Verify FSL / FLIRT
# ============================================================

if [ ! -x "${COCANOT_PREFIX}/bin/flirt" ]; then
    echo "ERROR: FSL FLIRT was not found:"
    echo "${COCANOT_PREFIX}/bin/flirt"
    exit 1
fi

echo "FSL FLIRT installation verified."


# ============================================================
# Verify required packaged files exist
# ============================================================

if [ ! -f "${ICON_SOURCE}" ]; then
    echo "ERROR: CoCANoT icon was not found:"
    echo "${ICON_SOURCE}"
    exit 1
fi

if [ ! -f "${UNINSTALL_SCRIPT_SOURCE}" ]; then
    echo "ERROR: CoCANoT uninstall script was not found:"
    echo "${UNINSTALL_SCRIPT_SOURCE}"
    exit 1
fi

chmod +x "${UNINSTALL_SCRIPT_SOURCE}"


# ============================================================
# Create pipeline application
# ============================================================

create_app() {

    APP_NAME="$1"
    BUNDLE_ID="$2"
    DASHBOARD="$3"
    USE_FSL="$4"

    APP_PATH="${APPLICATIONS_DIR}/${APP_NAME}.app"


    # --------------------------------------------------------
    # Create application bundle
    # --------------------------------------------------------

    rm -rf "${APP_PATH}"

    mkdir -p "${APP_PATH}/Contents/MacOS"
    mkdir -p "${APP_PATH}/Contents/Resources"


    # --------------------------------------------------------
    # Add CoCANoT icon
    # --------------------------------------------------------

    cp "${ICON_SOURCE}" \
       "${APP_PATH}/Contents/Resources/logo.icns"


    # --------------------------------------------------------
    # Info.plist
    # --------------------------------------------------------

    cat > "${APP_PATH}/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>

<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">

<plist version="1.0">

<dict>

    <key>CFBundleName</key>
    <string>${APP_NAME}</string>

    <key>CFBundleDisplayName</key>
    <string>${APP_NAME}</string>

    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}</string>

    <key>CFBundleVersion</key>
    <string>0.1.0</string>

    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>

    <key>CFBundleExecutable</key>
    <string>launch</string>

    <key>CFBundleIconFile</key>
    <string>logo.icns</string>

    <key>NSHighResolutionCapable</key>
    <true/>

</dict>

</plist>
EOF


    # --------------------------------------------------------
    # Create pipeline launcher
    # --------------------------------------------------------

    if [ "${USE_FSL}" = "yes" ]; then

        cat > "${APP_PATH}/Contents/MacOS/launch" <<EOF
#!/bin/bash

PREFIX="${COCANOT_PREFIX}"

export PATH="\${PREFIX}/bin:\${PATH}"
export PYTHONPATH="\${PREFIX}/app:\${PYTHONPATH:-}"

export FSLDIR="\${PREFIX}"

exec "\${PREFIX}/bin/python" \
    "\${PREFIX}/app/${DASHBOARD}"
EOF

    else

        cat > "${APP_PATH}/Contents/MacOS/launch" <<EOF
#!/bin/bash

PREFIX="${COCANOT_PREFIX}"

export PATH="\${PREFIX}/bin:\${PATH}"
export PYTHONPATH="\${PREFIX}/app:\${PYTHONPATH:-}"

exec "\${PREFIX}/bin/python" \
    "\${PREFIX}/app/${DASHBOARD}"
EOF

    fi

    chmod +x "${APP_PATH}/Contents/MacOS/launch"
}


# ============================================================
# Create clickable CoCANoT uninstaller
# ============================================================

create_uninstaller_app() {

    APP_NAME="Uninstall CoCANoT"
    APP_PATH="${APPLICATIONS_DIR}/${APP_NAME}.app"


    # --------------------------------------------------------
    # Create application bundle
    # --------------------------------------------------------

    rm -rf "${APP_PATH}"

    mkdir -p "${APP_PATH}/Contents/MacOS"
    mkdir -p "${APP_PATH}/Contents/Resources"


    # --------------------------------------------------------
    # Add CoCANoT icon
    # --------------------------------------------------------

    cp "${ICON_SOURCE}" \
       "${APP_PATH}/Contents/Resources/logo.icns"


    # --------------------------------------------------------
    # Info.plist
    # --------------------------------------------------------

    cat > "${APP_PATH}/Contents/Info.plist" <<EOF
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
    <string>0.1.0</string>

    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>

    <key>CFBundleExecutable</key>
    <string>launch</string>

    <key>CFBundleIconFile</key>
    <string>logo.icns</string>

    <key>NSHighResolutionCapable</key>
    <true/>

</dict>

</plist>
EOF


    # --------------------------------------------------------
    # Create clickable launcher
    #
    # The Constructor installation prefix is written into this
    # launcher at installation time, so no username or
    # developer-specific path is hardcoded.
    # --------------------------------------------------------

    cat > "${APP_PATH}/Contents/MacOS/launch" <<EOF
#!/bin/bash

COCANOT_PREFIX="${COCANOT_PREFIX}"

UNINSTALL_SCRIPT="\${COCANOT_PREFIX}/app/uninstall_macos.sh"


# ------------------------------------------------------------
# Ask for confirmation
# ------------------------------------------------------------

RESULT=\$(/usr/bin/osascript <<'APPLESCRIPT'
try
    display dialog "Are you sure you want to uninstall CoCANoT Pipelines?

This will remove CoCANoT Imaging, CoCANoT Electrophysiology, and their bundled software dependencies.

Your imaging data, electrophysiology data, BIDS outputs, derivatives, and other research data will NOT be deleted." buttons {"Cancel", "Uninstall"} default button "Uninstall" cancel button "Cancel" with title "Uninstall CoCANoT"

    return button returned of result

on error number -128
    return "Cancel"
end try
APPLESCRIPT
)


if [ "\${RESULT}" != "Uninstall" ]; then
    exit 0
fi


# ------------------------------------------------------------
# Verify uninstall script exists
# ------------------------------------------------------------

if [ ! -f "\${UNINSTALL_SCRIPT}" ]; then

    /usr/bin/osascript <<'APPLESCRIPT'
display dialog "The CoCANoT uninstaller could not be found.

Please contact the CoCANoT development team." buttons {"OK"} default button "OK" with icon caution with title "CoCANoT Uninstaller"
APPLESCRIPT

    exit 1
fi


# ------------------------------------------------------------
# Copy script to /tmp
#
# This allows the script to remove the CoCANoT environment
# that originally contained uninstall_macos.sh.
# ------------------------------------------------------------

TEMP_SCRIPT=\$(mktemp "/tmp/cocanot-uninstall.XXXXXX")

cp "\${UNINSTALL_SCRIPT}" "\${TEMP_SCRIPT}"

chmod 700 "\${TEMP_SCRIPT}"


# ------------------------------------------------------------
# Request macOS administrator authorization and uninstall
# ------------------------------------------------------------

/usr/bin/osascript <<APPLESCRIPT
do shell script "/bin/bash " & quoted form of "\${TEMP_SCRIPT}" & " --yes --prefix " & quoted form of "\${COCANOT_PREFIX}" with administrator privileges
APPLESCRIPT

UNINSTALL_STATUS=\$?


# ------------------------------------------------------------
# Clean temporary file
# ------------------------------------------------------------

rm -f "\${TEMP_SCRIPT}" 2>/dev/null || true


# ------------------------------------------------------------
# Report result
# ------------------------------------------------------------

if [ "\${UNINSTALL_STATUS}" -eq 0 ]; then

    /usr/bin/osascript <<'APPLESCRIPT'
display dialog "CoCANoT Pipelines was removed successfully.

Your research data was not modified." buttons {"OK"} default button "OK" with title "CoCANoT Uninstaller"
APPLESCRIPT

else

    /usr/bin/osascript <<'APPLESCRIPT'
display dialog "CoCANoT could not be completely removed.

Please contact the CoCANoT development team." buttons {"OK"} default button "OK" with icon caution with title "CoCANoT Uninstaller"
APPLESCRIPT

fi

exit 0
EOF

    chmod +x "${APP_PATH}/Contents/MacOS/launch"
}


# ============================================================
# Create CoCANoT applications
# ============================================================

create_app \
    "CoCANoT Imaging" \
    "org.cocanot.imaging" \
    "ImagingPipeline/dashboard.py" \
    "yes"


create_app \
    "CoCANoT Electrophysiology" \
    "org.cocanot.electrophysiology" \
    "ElectrophysiologyPipeline/dashboard.py" \
    "no"


create_uninstaller_app


# ============================================================
# Final verification
# ============================================================

echo ""
echo "============================================"
echo "CoCANoT post-install setup completed."
echo "============================================"
echo ""
echo "Verified:"
echo "  - Python"
echo "  - PyDeface"
echo "  - FSL / FLIRT"
echo "  - CoCANoT Imaging"
echo "  - CoCANoT Electrophysiology"
echo "  - CoCANoT Uninstaller"
echo ""

exit 0