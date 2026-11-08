#!/bin/sh
# Rebuild tools/bin/voz-engine (about 20 s; fetches the Desert Ant SDK from GitHub, then
# deletes the compiler leftovers). Only needed after changing main.swift or the SDK version;
# the repo ships a signed binary, and this one is signed ad hoc for your own Mac. Needs Xcode
# or the Command Line Tools (swift) on an Apple silicon Mac running macOS 26 or newer.
# Build paths are mapped away and debug symbols stripped, so no folder name ends up in it.
set -eu
PKG="$(cd "$(dirname "$0")" && pwd -P)"
BIN="$PKG/../bin"
SCRATCH="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$SCRATCH"' EXIT
swift build -c release --package-path "$PKG" --scratch-path "$SCRATCH" \
  -Xswiftc -file-prefix-map -Xswiftc "$PKG=." -Xswiftc -file-prefix-map -Xswiftc "$SCRATCH=." \
  -Xcc "-ffile-prefix-map=$PKG=." -Xcc "-ffile-prefix-map=$SCRATCH=."
mkdir -p "$BIN"
cp "$SCRATCH/release/voz-engine" "$BIN/voz-engine.tmp"
strip -S -x "$BIN/voz-engine.tmp"
codesign --force --sign - --identifier voz-engine "$BIN/voz-engine.tmp" 2>/dev/null
mv "$BIN/voz-engine.tmp" "$BIN/voz-engine"
echo "built $BIN/voz-engine"
