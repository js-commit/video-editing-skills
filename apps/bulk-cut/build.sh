#!/bin/zsh
# Build BulkCut.app with swiftc (no Xcode project needed).
#
#   apps/bulk-cut/build.sh            release build -> apps/bulk-cut/build/BulkCut.app
#   apps/bulk-cut/build.sh --debug    -Onone with debug info
#   apps/bulk-cut/build.sh --install  also copy it to ~/Applications and register it
#                                     with Launch Services (Dock, Spotlight, "Open With")
#   apps/bulk-cut/build.sh --portable universal, stripped, no build-machine paths
#                                     (what tools/release/sign_release.sh signs)
#
# The repo ships a signed copy in apps/bulk-cut/prebuilt/. You only need this
# script after changing the source; your own build/ copy is then used first.
#
# Needs the Swift toolchain from Xcode or the Command Line Tools
# (xcode-select --install) and macOS 15 or later. Nothing is installed
# unless you pass --install. BULKCUT_BUILD_DIR overrides the output folder.
set -euo pipefail
cd "$(dirname "$0")"
HERE=$PWD
BUILD=${BULKCUT_BUILD_DIR:-$HERE/build}
APP=$BUILD/BulkCut.app
INSTALLED=$HOME/Applications/BulkCut.app
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
    -target "${ARCH}-apple-macos15.0" \
    -module-name BulkCut \
    Sources/*.swift \
    -o "$BUILD/BulkCut.$ARCH" \
    -framework SwiftUI -framework AppKit -framework AVFoundation -framework AVKit
  SLICES+=("$BUILD/BulkCut.$ARCH")
done
lipo -create "${SLICES[@]}" -output "$APP/Contents/MacOS/BulkCut"
(( PORTABLE )) && strip -S -x "$APP/Contents/MacOS/BulkCut"
cp Info.plist "$APP/Contents/Info.plist"

# The icon is drawn at build time (scripts/make_icon.swift); the repo keeps no
# icon image source (only the signed copy in prebuilt/ carries the built .icns).
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
