#!/usr/bin/env bash
set -euo pipefail
plico_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$plico_root"
export PATH="$plico_root/build/venv/bin:/opt/homebrew/bin:$PATH"
jobs="${PLICO_BUILD_JOBS:-1}"
case "$jobs" in ''|*[!0-9]*) echo 'PLICO_BUILD_JOBS must be a positive integer.' >&2; exit 2 ;; esac
if [ "$jobs" -ne 1 ]; then
  echo 'This 24 GB development host is restricted to one build worker after memory exhaustion.' >&2
  exit 2
fi
if [ ! -f build/src/out/Default/build.ninja ]; then
  echo 'Run scripts/prepare-build.sh first.' >&2
  exit 1
fi
targets=("$@")
if [ "$#" -eq 0 ]; then targets=(chrome chromedriver); fi
for target in "${targets[@]}"; do
  case "$target" in -*) echo 'Only build target names are accepted.' >&2; exit 2 ;; esac
done
export SISO_PATH="$plico_root/build/src/third_party/siso/cipd/siso"
cd build/src
exec python3 "$plico_root/scripts/memory-guard.py" \
  --log "$plico_root/build/logs/build-memory.jsonl" \
  -- python3 third_party/depot_tools/autoninja.py -C out/Default -j "$jobs" "${targets[@]}"
