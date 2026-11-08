#!/bin/zsh
# Copy EditReview and/or BulkCut to ~/Applications and register them with macOS, so Finder's
# "Open With", the Dock and `open -a` find them. Optional: both also run straight from the repo.
#
#   apps/install_apps.sh                 both apps
#   apps/install_apps.sh edit-review     one app (edit-review or bulk-cut)
#
# Uses your own build/ copy when there is one, else the signed prebuilt/ copy. An older
# installed copy is moved to a temporary folder, which macOS clears by itself.
set -euo pipefail
HERE=${0:A:h}
REPO=${HERE:h}
DEST=${APPS_INSTALL_DIR:-$HOME/Applications}
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
[[ $# -gt 0 ]] && WANT=("$@") || WANT=(edit-review bulk-cut)
mkdir -p "$DEST"
for name in $WANT; do
  case $name in
    edit-review) APP=EditReview ;;
    bulk-cut) APP=BulkCut ;;
    *) echo "usage: $0 [edit-review] [bulk-cut]" >&2; exit 2 ;;
  esac
  SRC=$HERE/$name/build/$APP.app
  [[ -d $SRC ]] || SRC=$HERE/$name/prebuilt/$APP.app
  [[ -d $SRC ]] || { echo "$APP not found in $HERE/$name" >&2; exit 1; }
  [[ -e $DEST/$APP.app ]] && mv "$DEST/$APP.app" "$(mktemp -d)/"
  ditto "$SRC" "$DEST/$APP.app"
  "$LSREGISTER" -f "$DEST/$APP.app"
  if [[ $name == edit-review ]]; then     # an installed copy cannot find the repo from its own place
    defaults write "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$DEST/$APP.app/Contents/Info.plist")" repoPath "$REPO"
  fi
  echo "installed $DEST/$APP.app"
done
