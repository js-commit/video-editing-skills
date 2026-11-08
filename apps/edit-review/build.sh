#!/bin/zsh
# Build EditReview.app with swiftc (no Xcode project needed).
#
#   apps/edit-review/build.sh            release build -> apps/edit-review/build/EditReview.app
#   apps/edit-review/build.sh --debug    -Onone with debug info
#   apps/edit-review/build.sh --install  also copy it to ~/Applications and register it
#                                        with Launch Services (so Finder can open videos with it)
#   apps/edit-review/build.sh --portable universal, stripped, no build-machine paths
#                                        (what tools/release/sign_release.sh signs)
#
# The repo ships a signed copy in apps/edit-review/prebuilt/. You only need this
# script after changing the source; your own build/ copy is then used first.
#
# Needs the Swift toolchain from Xcode or the Command Line Tools
# (xcode-select --install) and macOS 14 or later. Nothing is installed
# unless you pass --install. EDIT_REVIEW_BUILD_DIR overrides the output folder.
set -euo pipefail
cd "$(dirname "$0")"
HERE=$PWD
REPO=${HERE:h:h}
BUILD=${EDIT_REVIEW_BUILD_DIR:-$HERE/build}
APP=$BUILD/EditReview.app
INSTALLED=$HOME/Applications/EditReview.app
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
OPT=(-O)
INSTALL=0
PORTABLE=0
for arg in "$@"; do
  case $arg in
    --debug) OPT=(-Onone -g) ;;
    --install) INSTALL=1 ;;
    --portable) PORTABLE=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "usage: $0 [--debug] [--install] [--portable]" >&2; exit 2 ;;
  esac
done
if ! command -v swiftc >/dev/null; then
  echo "swiftc not found: install Xcode or the Command Line Tools (xcode-select --install)" >&2
  exit 1
fi
ARCHS=($(uname -m))
(( PORTABLE )) && ARCHS=(arm64 x86_64)

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
SLICES=()
for ARCH in $ARCHS; do
  swiftc "${OPT[@]}" -parse-as-library -file-prefix-map "$HERE=." \
    -target "${ARCH}-apple-macos14.0" \
    -module-name EditReview \
    Sources/*.swift \
    -o "$BUILD/EditReview.$ARCH" \
    -framework SwiftUI -framework AppKit -framework AVFoundation -framework AVKit
  SLICES+=("$BUILD/EditReview.$ARCH")
done
lipo -create "${SLICES[@]}" -output "$APP/Contents/MacOS/EditReview"
(( PORTABLE )) && strip -S -x "$APP/Contents/MacOS/EditReview"
cp Info.plist "$APP/Contents/Info.plist"
# Finder launches apps without the shell's PATH and an installed copy cannot
# find the repo from its own location: record where the repo is, so the app
# can run tools/transcribe.py and scripts/export_cuts.py.
(( PORTABLE )) || /usr/libexec/PlistBuddy -c "Add :EditReviewRepo string $REPO" "$APP/Contents/Info.plist"

# The icon is drawn at build time (scripts/make_icon.swift); no image files in the repo.
ICONSET=$BUILD/AppIcon.iconset
if swiftc -O scripts/make_icon.swift -o "$BUILD/make_icon" 2>/dev/null \
   && "$BUILD/make_icon" "$ICONSET" >/dev/null \
   && iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"; then
  :
else
  echo "note: could not draw the icon; the app uses the generic one" >&2
fi
rm -rf "$ICONSET" "$BUILD/make_icon"

printf 'APPL????' > "$APP/Contents/PkgInfo"
# Ad-hoc signature: runs on this Mac without prompts (the app needs no
# privacy permission). Not for handing to other people.
codesign --force --sign - "$APP" >/dev/null
echo "built $APP"

if (( INSTALL )); then
  mkdir -p "$HOME/Applications"
  rm -rf "$INSTALLED"             # new inode: a running copy keeps its old binary
  ditto "$APP" "$INSTALLED"
  "$LSREGISTER" -f "$INSTALLED"
  echo "installed $INSTALLED"
fi
