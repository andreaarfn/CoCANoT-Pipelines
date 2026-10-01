#!/bin/bash
set -euo pipefail

ASSUME_YES=false
INSTALLED_PREFIX=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --yes)
            ASSUME_YES=true
            shift
            ;;
        --prefix)
            [ "$#" -ge 2 ] || { echo "ERROR: --prefix requires a path."; exit 1; }
            INSTALLED_PREFIX="$2"
            shift 2
            ;;
        *)
            echo "ERROR: Unknown argument: $1"
            exit 1
            ;;
    esac
done

CONSOLE_USER="$(/usr/bin/stat -f '%Su' /dev/console)"
if [ -z "${CONSOLE_USER}" ] || [ "${CONSOLE_USER}" = "root" ]; then
    echo "ERROR: Could not determine logged-in user."
    exit 1
fi

USER_HOME="$(
    /usr/bin/dscl . -read "/Users/${CONSOLE_USER}" NFSHomeDirectory 2>/dev/null |
    /usr/bin/awk '{print $2}'
)"

if [ -z "${USER_HOME}" ] || [ ! -d "${USER_HOME}" ]; then
    echo "ERROR: Could not determine logged-in user's home."
    exit 1
fi

safe_prefix() {
    case "$1" in
        "/Library/CoCANoT-Pipelines" | \
        "${USER_HOME}/Library/CoCANoT-Pipelines")
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

remove_owned_path() {
    TARGET="$1"
    LABEL="$2"

    [ -n "${TARGET}" ] || return 0

    if [ -e "${TARGET}" ] || [ -L "${TARGET}" ]; then
        echo "Removing ${LABEL}: ${TARGET}"
        /bin/rm -rf -- "${TARGET}"
    fi
}

if [ "${ASSUME_YES}" != true ]; then
    echo "This removes CoCANoT and all CoCANoT-owned local application data."
    printf "Continue? [y/N]: "
    read -r REPLY
    case "${REPLY}" in
        y|Y|yes|YES) ;;
        *) exit 0 ;;
    esac
fi

# Applications created by the CoCANoT installer.
remove_owned_path "/Applications/CoCANoT.app" "CoCANoT application"

# Per-user CoCANoT-owned state. This intentionally removes the local metadata
# database and saved pipeline settings as part of a full uninstall.
remove_owned_path "${USER_HOME}/.cocanot" "CoCANoT local database and settings"
remove_owned_path "${USER_HOME}/Library/Application Support/CoCANoT" "CoCANoT application support"
remove_owned_path "${USER_HOME}/Library/Caches/org.cocanot.app" "CoCANoT cache"
remove_owned_path "${USER_HOME}/Library/Caches/CoCANoT" "CoCANoT cache"
remove_owned_path "${USER_HOME}/Library/Logs/CoCANoT" "CoCANoT logs"
remove_owned_path "${USER_HOME}/Library/Saved Application State/org.cocanot.app.savedState" "CoCANoT saved state"
remove_owned_path "${USER_HOME}/Library/Preferences/org.cocanot.app.plist" "CoCANoT preferences"
remove_owned_path "${USER_HOME}/Library/Preferences/org.cocanot.uninstaller.plist" "CoCANoT uninstaller preferences"

# Remove only the exact Constructor prefix passed by our own uninstaller and
# only when it matches one of the two approved CoCANoT installation paths.
if [ -n "${INSTALLED_PREFIX}" ]; then
    if safe_prefix "${INSTALLED_PREFIX}"; then
        remove_owned_path "${INSTALLED_PREFIX}" "CoCANoT private runtime and dependencies"
    else
        echo "ERROR: Refusing to remove unexpected prefix: ${INSTALLED_PREFIX}"
        exit 1
    fi
fi

# Also remove a stale copy in the other supported location if present.
for PREFIX_CANDIDATE in \
    "/Library/CoCANoT-Pipelines" \
    "${USER_HOME}/Library/CoCANoT-Pipelines"
do
    if safe_prefix "${PREFIX_CANDIDATE}"; then
        remove_owned_path "${PREFIX_CANDIDATE}" "CoCANoT private runtime and dependencies"
    fi
done

# Forget only package receipts whose identifiers contain cocanot.
while IFS= read -r RECEIPT; do
    [ -n "${RECEIPT}" ] || continue
    echo "Forgetting package receipt: ${RECEIPT}"
    /usr/sbin/pkgutil --forget "${RECEIPT}" >/dev/null 2>&1 || true
done < <(/usr/sbin/pkgutil --pkgs 2>/dev/null | /usr/bin/grep -i 'cocanot' || true)

# The running uninstaller app removes itself last.
remove_owned_path "/Applications/Uninstall CoCANoT.app" "CoCANoT uninstaller"

echo "CoCANoT was completely removed."
echo "User-selected source, derivatives, and BIDS output folders were not modified."
exit 0
