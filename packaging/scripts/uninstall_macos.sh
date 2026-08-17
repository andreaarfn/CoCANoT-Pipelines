#!/bin/bash

# ============================================================
# CoCANoT Pipelines macOS Uninstaller
#
# Removes:
#   - CoCANoT Imaging.app
#   - CoCANoT Electrophysiology.app
#   - CoCANoT bundled environment and dependencies
#   - CoCANoT package receipts
#   - Uninstall CoCANoT.app
#
# Does NOT remove:
#   - User research data
#   - BIDS outputs
#   - Imaging/EEG source data
#   - User-selected derivatives folders
# ============================================================


ASSUME_YES=false
INSTALLED_PREFIX=""


# ------------------------------------------------------------
# Parse arguments
# ------------------------------------------------------------

while [ "$#" -gt 0 ]; do
    case "$1" in
        --yes)
            ASSUME_YES=true
            shift
            ;;

        --prefix)
            if [ "$#" -lt 2 ]; then
                echo "ERROR: --prefix requires a path."
                exit 1
            fi

            INSTALLED_PREFIX="$2"
            shift 2
            ;;

        *)
            shift
            ;;
    esac
done


# ------------------------------------------------------------
# Determine the currently logged-in macOS user
# ------------------------------------------------------------

CONSOLE_USER="$(stat -f '%Su' /dev/console)"

if [ -z "${CONSOLE_USER}" ] || [ "${CONSOLE_USER}" = "root" ]; then
    echo "ERROR: Could not determine the logged-in user."
    exit 1
fi


USER_HOME="$(
    dscl . -read "/Users/${CONSOLE_USER}" NFSHomeDirectory 2>/dev/null |
    awk '{print $2}'
)"

if [ -z "${USER_HOME}" ] || [ ! -d "${USER_HOME}" ]; then
    echo "ERROR: Could not determine the logged-in user's home directory."
    exit 1
fi


# ------------------------------------------------------------
# Application locations
# ------------------------------------------------------------

APP_IMAGING_SYSTEM="/Applications/CoCANoT Imaging.app"
APP_EPHYS_SYSTEM="/Applications/CoCANoT Electrophysiology.app"
APP_UNINSTALL_SYSTEM="/Applications/Uninstall CoCANoT.app"

APP_IMAGING_USER="${USER_HOME}/Applications/CoCANoT Imaging.app"
APP_EPHYS_USER="${USER_HOME}/Applications/CoCANoT Electrophysiology.app"
APP_UNINSTALL_USER="${USER_HOME}/Applications/Uninstall CoCANoT.app"


# ------------------------------------------------------------
# Known CoCANoT installation locations
# ------------------------------------------------------------

INSTALL_LOCATIONS=()

# The best source is the actual Constructor prefix supplied
# by the installed Uninstall CoCANoT.app.
if [ -n "${INSTALLED_PREFIX}" ]; then
    INSTALL_LOCATIONS+=("${INSTALLED_PREFIX}")
fi

# Also check known user-level locations.
INSTALL_LOCATIONS+=(
    "${USER_HOME}/Library/cocanot-pipelines"
    "${USER_HOME}/Library/CoCANoT-Pipelines"
)

# Also check known system-level locations.
INSTALL_LOCATIONS+=(
    "/Library/cocanot-pipelines"
    "/Library/CoCANoT-Pipelines"
)


# ------------------------------------------------------------
# Safety check for installation paths
# ------------------------------------------------------------

is_safe_cocanot_path() {
    TARGET="$1"

    case "${TARGET}" in
        "${USER_HOME}/Library/cocanot-pipelines" | \
        "${USER_HOME}/Library/CoCANoT-Pipelines" | \
        "/Library/cocanot-pipelines" | \
        "/Library/CoCANoT-Pipelines")
            return 0
            ;;

        *)
            return 1
            ;;
    esac
}


# ------------------------------------------------------------
# Confirmation for manual/scripted use
# ------------------------------------------------------------

if [ "${ASSUME_YES}" != true ]; then

    echo ""
    echo "CoCANoT Pipelines Uninstaller"
    echo "============================="
    echo ""
    echo "This will remove:"
    echo ""
    echo "  - CoCANoT Imaging"
    echo "  - CoCANoT Electrophysiology"
    echo "  - CoCANoT's bundled Python environment"
    echo "  - CoCANoT's bundled software dependencies"
    echo "  - CoCANoT installer receipts"
    echo ""
    echo "Your imaging, electrophysiology, BIDS, derivatives,"
    echo "and other research data will NOT be deleted."
    echo ""

    read -r -p "Continue with uninstall? [y/N]: " RESPONSE

    case "${RESPONSE}" in
        y|Y|yes|YES)
            ;;
        *)
            echo ""
            echo "Uninstall cancelled."
            exit 0
            ;;
    esac
fi


echo ""
echo "Removing CoCANoT Pipelines..."
echo ""


# ------------------------------------------------------------
# Helper for removing files/directories
# ------------------------------------------------------------

remove_path() {
    TARGET="$1"
    DESCRIPTION="$2"

    if [ -e "${TARGET}" ]; then
        echo "Removing ${DESCRIPTION}..."
        rm -rf "${TARGET}"
    fi
}


# ------------------------------------------------------------
# Remove CoCANoT applications
# ------------------------------------------------------------

remove_path \
    "${APP_IMAGING_SYSTEM}" \
    "CoCANoT Imaging"

remove_path \
    "${APP_EPHYS_SYSTEM}" \
    "CoCANoT Electrophysiology"

remove_path \
    "${APP_IMAGING_USER}" \
    "user-level CoCANoT Imaging"

remove_path \
    "${APP_EPHYS_USER}" \
    "user-level CoCANoT Electrophysiology"


# ------------------------------------------------------------
# Remove bundled CoCANoT environment
# ------------------------------------------------------------

for INSTALL_DIR in "${INSTALL_LOCATIONS[@]}"; do

    if [ -z "${INSTALL_DIR}" ]; then
        continue
    fi

    if ! is_safe_cocanot_path "${INSTALL_DIR}"; then
        echo "Skipping unexpected installation path:"
        echo "  ${INSTALL_DIR}"
        continue
    fi

    if [ -e "${INSTALL_DIR}" ]; then
        echo "Removing CoCANoT installation:"
        echo "  ${INSTALL_DIR}"

        rm -rf "${INSTALL_DIR}"
    fi

done


# ------------------------------------------------------------
# Remove CoCANoT package receipts
# ------------------------------------------------------------

echo "Removing CoCANoT installer receipts..."

while IFS= read -r RECEIPT; do

    if [ -n "${RECEIPT}" ]; then
        echo "  Forgetting ${RECEIPT}"

        pkgutil --forget "${RECEIPT}" \
            >/dev/null 2>&1 || true
    fi

done < <(
    pkgutil --pkgs 2>/dev/null |
    grep -i 'cocanot' || true
)


# ------------------------------------------------------------
# Verify installation environment is gone
# ------------------------------------------------------------

REMAINS=false

for INSTALL_DIR in "${INSTALL_LOCATIONS[@]}"; do

    if [ -z "${INSTALL_DIR}" ]; then
        continue
    fi

    if ! is_safe_cocanot_path "${INSTALL_DIR}"; then
        continue
    fi

    if [ -e "${INSTALL_DIR}" ]; then
        echo ""
        echo "WARNING: Could not remove:"
        echo "  ${INSTALL_DIR}"

        REMAINS=true
    fi

done


if [ "${REMAINS}" = true ]; then

    echo ""
    echo "CoCANoT could not be completely removed."
    echo "Please contact the CoCANoT development team."

    exit 1
fi


# ------------------------------------------------------------
# Remove the clickable uninstaller itself
# ------------------------------------------------------------

rm -rf "${APP_UNINSTALL_SYSTEM}" \
    2>/dev/null || true

rm -rf "${APP_UNINSTALL_USER}" \
    2>/dev/null || true


# ------------------------------------------------------------
# Complete
# ------------------------------------------------------------

echo ""
echo "========================================"
echo "CoCANoT Pipelines was removed successfully."
echo "========================================"
echo ""
echo "Your research data was not modified."
echo ""

exit 0