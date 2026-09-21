#!/usr/bin/env bash
set -euo pipefail
plico_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
profile="${1:-qualification}"
if [ "$#" -gt 0 ]; then shift; fi
case "$profile" in
  ''|*[!a-zA-Z0-9_-]*) echo 'Profile name must contain only letters, digits, - or _.' >&2; exit 2 ;;
esac
for argument in "$@"; do
  case "$argument" in
    --user-data-dir*|--profile-directory*)
      echo 'Profile overrides are forbidden in the isolated launcher.' >&2; exit 2 ;;
  esac
done
profile_root="$plico_root/build/profiles"
profile_path="$profile_root/$profile"
python3 - "$profile_root" "$profile_path" <<'PY'
from pathlib import Path
import sys
root, profile = map(Path, sys.argv[1:])
if root.is_symlink() or profile.is_symlink():
    raise SystemExit('Refusing a symlinked qualification profile.')
root.mkdir(parents=True, exist_ok=True)
if not profile.resolve().is_relative_to(root.resolve()):
    raise SystemExit('Profile escapes the qualification directory.')
profile.mkdir(exist_ok=True)
PY
app="$plico_root/build/src/out/Default/plico.app/Contents/MacOS/plico"
if [ ! -x "$app" ]; then
  app="$plico_root/build/src/out/Default/Helium.app/Contents/MacOS/Helium"
fi
if [ ! -x "$app" ]; then echo 'No compiled browser exists yet.' >&2; exit 1; fi
debug_args=()
if [ "${PLICO_CDP:-0}" = 1 ]; then
  debug_args+=(--remote-debugging-port=0 --remote-debugging-address=127.0.0.1)
fi
exec "$app" \
  --user-data-dir="$profile_path" \
  --no-first-run --no-default-browser-check --use-mock-keychain \
  "${debug_args[@]}" "$@"
