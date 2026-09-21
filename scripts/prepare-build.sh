#!/usr/bin/env bash
# Prepare a fresh, pinned upstream tree. Never reset an existing source checkout.
set -euo pipefail
plico_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$plico_root"
export PATH="/opt/homebrew/bin:$PATH"
for tool in python3.13 greadlink quilt wget xcodebuild; do
  command -v "$tool" >/dev/null || { echo "Missing prerequisite: $tool" >&2; exit 1; }
done
xcrun metal --version >/dev/null
python3 - <<'PY'
import json, subprocess
from pathlib import Path
pin=json.loads(Path('config/upstream.json').read_text())
subprocess.run(['git','merge-base','--is-ancestor',pin['platform_commit'],'HEAD'],check=True)
core=subprocess.check_output(['git','-C','helium-chromium','rev-parse','HEAD'],text=True).strip()
if core != pin['core_commit']: raise SystemExit('Core submodule does not match the pinned platform/core pair.')
PY
fingerprint="$(shasum -a 256 config/upstream.json | cut -d ' ' -f 1)"
marker="$plico_root/build/upstream-ready"
fresh=true
if [ -d build/src ]; then
  if [ ! -f "$marker" ] || [ "$(cat "$marker")" != "$fingerprint" ]; then
    echo 'Existing source tree has no matching preparation marker. Refusing to reset or overwrite it.' >&2
    exit 1
  fi
  fresh=false
fi
mkdir -p build/logs
if [ ! -x build/venv/bin/python3 ]; then python3.13 -m venv build/venv; fi
export PATH="$plico_root/build/venv/bin:$PATH"
if [ "$fresh" = true ]; then
  python3 -m pip install httplib2==0.22.0 requests==2.34.2 pillow==12.3.0
  ./retrieve_and_unpack_resource.sh -g arm64
fi
_root_dir="$plico_root"
source devutils/shared.sh
if [ "$fresh" = true ]; then
  python3 "$_main_repo/utils/prune_binaries.py" "$_src_dir" "$_main_repo/pruning.list"
  ./retrieve_and_unpack_resource.sh -t arm64
  python3 "$_main_repo/utils/patches.py" apply "$_src_dir" "$_main_repo/patches" "$_root_dir/patches"
  python3 "$_main_repo/utils/domain_substitution.py" apply -r "$_main_repo/domain_regex.list" -f "$_main_repo/domain_substitution.list" "$_src_dir"
  python3 "$_main_repo/utils/name_substitution.py" --sub -t "$_src_dir"
  python3 "$_main_repo/utils/i18n_apply.py" -t "$_src_dir"
  python3 "$_main_repo/utils/helium_version.py" --tree "$_main_repo" --platform-tree "$_root_dir" --chromium-tree "$_src_dir"
  helium_resources
fi
write_gn_args arm64 dev false
python3 - "$_out_dir/args.gn" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
p.write_text(p.read_text().replace('symbol_level=1\n','symbol_level=0\n')+
             '\n# Pinned Clang rejects module names on precompiled header inputs.\n'
             'enable_precompiled_headers = false\n')
PY
cd "$_src_dir"
___helium_install_cipd_deps
___helium_configure_siso
"$_gn_path" gen "$_out_dir" --fail-on-unused-args --export-compile-commands
printf '%s\n' "$fingerprint" > "$marker"
