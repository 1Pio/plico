#!/usr/bin/env bash
set -euo pipefail
plico_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$plico_root"
export PATH="$plico_root/build/venv/bin:/opt/homebrew/bin:$PATH"
jobs="${PLICO_BUILD_JOBS:-2}"
case "$jobs" in
  1|2|3) ;;
  *) echo 'PLICO_BUILD_JOBS must be 1, 2 or 3; higher concurrency is not qualified on this 24 GB host.' >&2; exit 2 ;;
esac
if [ ! -f build/src/out/Default/build.ninja ]; then
  echo 'Run scripts/prepare-build.sh first.' >&2
  exit 1
fi
targets=("$@")
if [ "$#" -eq 0 ]; then targets=(chrome chromedriver); fi
for target in "${targets[@]}"; do
  case "$target" in -*) echo 'Only build target names are accepted.' >&2; exit 2 ;; esac
done
guard_args=(--log "$plico_root/build/logs/build-memory.jsonl")
case "${PLICO_GUARD_MODE:-interactive}" in
  interactive) ;;
  independent)
    guard_args+=(--independent --require-ac-power
      --wait-for-headroom-seconds "${PLICO_WAIT_FOR_HEADROOM_SECONDS:-43200}"
      --max-runtime-seconds "${PLICO_MAX_RUNTIME_SECONDS:-0}"
      --status "$plico_root/build/logs/unattended-status.json") ;;
  *) echo 'Unknown PLICO_GUARD_MODE.' >&2; exit 2 ;;
esac
export SISO_PATH="$plico_root/build/src/third_party/siso/cipd/siso"
# Keep generator CPU discovery serial. Explicit Siso concurrency avoids
# autoninja ignoring -j > 1 when PYTHON_CPU_COUNT=1 is inherited from the guard.
cd build/src
exec python3 "$plico_root/scripts/memory-guard.py" \
  "${guard_args[@]}" \
  -- python3 third_party/depot_tools/autoninja.py -C out/Default -local_jobs="$jobs" \
  -fs_state_compression_threads=1 "${targets[@]}"
