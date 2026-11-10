#!/usr/bin/env bash
# CoCANoT Linux uninstall. Only touches paths owned by the current user.
set -euo pipefail

PREFIX="${HOME}/.local/share/CoCANoT/runtime"
DATA_ROOT="${HOME}/.cocanot"
APP_LINK="${HOME}/.local/bin/cocanot"
UNINSTALL_LINK="${HOME}/.local/bin/cocanot-uninstall"
DESKTOP_ENTRY="${HOME}/.local/share/applications/org.cocanot.desktop"

if [ "$(id -u)" -eq 0 ]; then
  echo "Do not run this per-user uninstaller as root or with sudo." >&2
  exit 1
fi

read -r -p "Uninstall CoCANoT's Linux application and bundled runtime? [y/N]: " CONFIRM
case "$CONFIRM" in y|Y|yes|YES) ;; *) echo "Cancelled. No changes made."; exit 0;; esac

read -r -p "ALSO permanently delete local patient records, attachments, and settings (~/.cocanot)? [y/N]: " DELETE_DATA
case "$DELETE_DATA" in y|Y|yes|YES) DELETE_DATA=yes;; *) DELETE_DATA=no;; esac

# Protect against an unexpected symlink that redirects deletion elsewhere.
safe_remove() {
  local target="$1" label="$2"
  if [ -L "$target" ]; then
    echo "Refusing to remove symlinked $label: $target" >&2
    return 1
  fi
  if [ -e "$target" ]; then
    echo "Removing $label: $target"
    rm -rf -- "$target"
  fi
}
# Refuse redirected ancestors for application and data folders.
for ancestor in "$HOME/.local" "$HOME/.local/share" "$HOME/.local/share/CoCANoT"; do
  if [ -L "$ancestor" ]; then
    echo "Refusing to remove from symlinked parent directory: $ancestor" >&2
    exit 1
  fi
done

# Only remove launchers whose contents identify the CoCANoT install.
if [ -f "$APP_LINK" ] && [ ! -L "$APP_LINK" ] &&
   grep -Fq "$PREFIX" "$APP_LINK"; then
  rm -f -- "$APP_LINK"
fi
if [ -f "$DESKTOP_ENTRY" ] && [ ! -L "$DESKTOP_ENTRY" ] &&
   grep -Fq "$APP_LINK" "$DESKTOP_ENTRY"; then
  rm -f -- "$DESKTOP_ENTRY"
fi
if [ -f "$UNINSTALL_LINK" ] && [ ! -L "$UNINSTALL_LINK" ] &&
   grep -Fq "$PREFIX/payload/uninstall_linux.sh" "$UNINSTALL_LINK"; then
  rm -f -- "$UNINSTALL_LINK"
fi

if [ "$DELETE_DATA" = yes ]; then
  safe_remove "$DATA_ROOT" "CoCANoT local patient repository"
else
  echo "Preserved CoCANoT local patient repository: $DATA_ROOT"
fi
safe_remove "$PREFIX" "CoCANoT bundled runtime"
echo "CoCANoT Linux application removed."
echo "User-selected source files, derivatives, and BIDS output folders were not removed."
