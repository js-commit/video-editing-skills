#!/bin/zsh
# Maintainer only. Rebuild every prebuilt macOS program, sign it with a Developer ID, notarize
# it with Apple and put it in place. Users never run this; contributors don't need it either
# (each program's own build script makes an ad-hoc copy for their Mac).
#
#   SIGN_IDENTITY="Developer ID Application: ..." NOTARY_PROFILE=<profile> \
#     tools/release/sign_release.sh
#
# NOTARY_PROFILE names a notarytool keychain profile, stored once with
#   xcrun notarytool store-credentials <profile> --apple-id ... --team-id ...
# so the app-specific password stays in the keychain. Without it the script falls back to
# NOTARY_TOOL_APPLE_ID, NOTARY_TOOL_PASSWORD and NOTARY_TOOL_TEAM_ID (the password is then on
# notarytool's command line while it runs).
#
# Then check `git status` and commit the binaries. Stops if a program holds a build-machine path.
# The work folder is left in the system temp folder (public binaries only); macOS clears it.
set -euo pipefail
: ${SIGN_IDENTITY:?set SIGN_IDENTITY to your Developer ID Application identity}
if [[ -n ${NOTARY_PROFILE:-} ]]; then
  NOTARY_AUTH=(--keychain-profile "$NOTARY_PROFILE")
else
  if [[ -z ${NOTARY_TOOL_APPLE_ID:-} || -z ${NOTARY_TOOL_PASSWORD:-} || -z ${NOTARY_TOOL_TEAM_ID:-} ]]; then
    print -u2 -r -- "set NOTARY_PROFILE (a notarytool keychain profile), or all of NOTARY_TOOL_APPLE_ID, NOTARY_TOOL_PASSWORD and NOTARY_TOOL_TEAM_ID"
    exit 1
  fi
  NOTARY_AUTH=(--apple-id "$NOTARY_TOOL_APPLE_ID" --password "$NOTARY_TOOL_PASSWORD" --team-id "$NOTARY_TOOL_TEAM_ID")
fi
REPO=${0:A:h:h:h}
WORK=$(mktemp -d)
CLEARLAB=$REPO/.claude/skills/voice-clear/scripts/bin/clearlab
VOZ=$REPO/tools/bin/voz-engine
BUNDLE_PREFIX=io.github.js-commit

sign() { codesign --force --options runtime --timestamp --sign "$SIGN_IDENTITY" "$@"; }

notarize() {   # notarize <zip>: notarytool's exit code is unreliable, so read the status
  local out sub_status
  out=$(xcrun notarytool submit "$1" "${NOTARY_AUTH[@]}" --wait --output-format json)
  sub_status=$(print -r -- "$out" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("status"))')
  print -r -- "notarized ${1:t}: $sub_status"
  [[ $sub_status == Accepted ]] || { print -r -- "$out" >&2; exit 1; }
}

check_paths() {   # no build-machine paths in anything we ship
  python3 - "$@" <<'PY'
import pathlib, re, sys
bad = re.compile(rb"/(?:Users|Volumes|home)/[\x20-\x7e]+|/private/(?:var|tmp)/[\x20-\x7e]+|/var/folders/[\x20-\x7e]+")
hits = 0
for arg in sys.argv[1:]:
    p = pathlib.Path(arg)
    for f in ([p] if p.is_file() else [x for x in p.rglob("*") if x.is_file()]):
        for m in set(bad.findall(f.read_bytes())):
            print(f"{f}: {m[:120].decode()}", file=sys.stderr); hits += 1
sys.exit(1 if hits else 0)
PY
}

"$REPO/tools/voz-engine/build.sh"
python3 "$REPO/.claude/skills/voice-clear/scripts/voice_clear.py" build
for name in edit-review bulk-cut; do
  [[ $name == edit-review ]] && { APP=EditReview; VAR=EDIT_REVIEW_BUILD_DIR; } || { APP=BulkCut; VAR=BULKCUT_BUILD_DIR; }
  env $VAR="$WORK/$name" "$REPO/apps/$name/build.sh" --portable
done
check_paths "$VOZ" "$CLEARLAB" "$WORK/edit-review/EditReview.app" "$WORK/bulk-cut/BulkCut.app"

sign --identifier "$BUNDLE_PREFIX.voz-engine" "$VOZ"
sign --identifier "$BUNDLE_PREFIX.clearlab" "$CLEARLAB"
for bin in "$VOZ" "$CLEARLAB"; do
  ditto -c -k --keepParent "$bin" "$WORK/${bin:t}.zip"
  notarize "$WORK/${bin:t}.zip"
done

for name in edit-review bulk-cut; do
  [[ $name == edit-review ]] && APP=EditReview || APP=BulkCut
  sign "$WORK/$name/$APP.app"
  ditto -c -k --keepParent "$WORK/$name/$APP.app" "$WORK/$APP.zip"
  notarize "$WORK/$APP.zip"
  xcrun stapler staple "$WORK/$name/$APP.app"
  [[ -e $REPO/apps/$name/prebuilt ]] && mv "$REPO/apps/$name/prebuilt" "$WORK/old-prebuilt-$name"
  mkdir -p "$REPO/apps/$name/prebuilt"
  ditto "$WORK/$name/$APP.app" "$REPO/apps/$name/prebuilt/$APP.app"
done
echo "done: review with git status and commit the binaries"
