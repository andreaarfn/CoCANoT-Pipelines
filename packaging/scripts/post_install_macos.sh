#!/bin/bash
set -e

COCANOT_PREFIX="${PREFIX}"
APPLICATIONS_DIR="/Applications"

create_app() {
    APP_NAME="$1"
    BUNDLE_ID="$2"
    DASHBOARD="$3"
    USE_FSL="$4"

    APP_PATH="${APPLICATIONS_DIR}/${APP_NAME}.app"

    rm -rf "${APP_PATH}"
    mkdir -p "${APP_PATH}/Contents/MacOS"

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

    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

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

exit 0