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

if [ -z "${INSTALLED_PREFIX}" ]; then
    echo "ERROR: The installed CoCANoT prefix was not supplied."
    exit 1
fi

case "${INSTALLED_PREFIX}" in
    /Users/*/Library/CoCANoT/runtime)
        ;;
    *)
        echo "ERROR: Refusing to remove unexpected prefix: ${INSTALLED_PREFIX}"
        exit 1
        ;;
esac

USER_HOME="${INSTALLED_PREFIX%/Library/CoCANoT/runtime}"

if [ -z "${USER_HOME}" ] || [ "${USER_HOME}" = "${INSTALLED_PREFIX}" ] || [ ! -d "${USER_HOME}" ]; then
    echo "ERROR: Could not determine the owning user's home directory."
    exit 1
fi

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
    echo "This removes CoCANoT and all CoCANoT-owned local application data for this user."
    printf "Continue? [y/N]: "
    read -r REPLY
    case "${REPLY}" in
        y|Y|yes|YES) ;;
        *) exit 0 ;;
    esac
fi

# Apps installed only for this macOS user.
remove_owned_path "${USER_HOME}/Applications/CoCANoT.app" "CoCANoT application"

# CoCANoT-owned per-user state. This intentionally removes the local metadata
# database and saved pipeline settings as part of a full uninstall.
remove_owned_path "${USER_HOME}/.cocanot" "CoCANoT local database and settings"
remove_owned_path "${USER_HOME}/Library/Application Support/CoCANoT" "CoCANoT application support"
remove_owned_path "${USER_HOME}/Library/Caches/org.cocanot.app" "CoCANoT cache"
remove_owned_path "${USER_HOME}/Library/Caches/CoCANoT" "CoCANoT cache"
remove_owned_path "${USER_HOME}/Library/Logs/CoCANoT" "CoCANoT logs"
remove_owned_path "${USER_HOME}/Library/Saved Application State/org.cocanot.app.savedState" "CoCANoT saved state"
remove_owned_path "${USER_HOME}/Library/Preferences/org.cocanot.app.plist" "CoCANoT preferences"
remove_owned_path "${USER_HOME}/Library/Preferences/org.cocanot.uninstaller.plist" "CoCANoT uninstaller preferences"

# Remove the installer-owned private runtime only at the exact protected path.
remove_owned_path "${INSTALLED_PREFIX}" "CoCANoT private runtime and dependencies"

# Best-effort removal of CoCANoT package receipts. This does not elevate
# privileges; on managed systems where receipt removal is restricted, failure
# is harmless and the user-owned application/runtime are still removed.
while IFS= read -r RECEIPT; do
    [ -n "${RECEIPT}" ] || continue
    case "${RECEIPT}" in
        *cocanot*)
            echo "Forgetting package receipt: ${RECEIPT}"
            /usr/sbin/pkgutil --forget "${RECEIPT}" >/dev/null 2>&1 || true
            ;;
    esac
done < <(/usr/sbin/pkgutil --pkgs 2>/dev/null | /usr/bin/grep -i 'cocanot' || true)

# Remove the current user's uninstaller app last.
remove_owned_path "${USER_HOME}/Applications/Uninstall CoCANoT.app" "CoCANoT uninstaller"

echo "CoCANoT was completely removed for this user."
echo "User-selected source, derivatives, and BIDS output folders were not modified."
exit 0
