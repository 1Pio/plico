#!/usr/bin/env bash
set -euo pipefail
plico_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$plico_root/build/tests"
xcrun clang++ -std=c++20 -Wall -Wextra -Werror -pedantic -fno-exceptions \
  -fsanitize=address,undefined -g -I"$plico_root" \
  "$plico_root/plico/core/navigator_model.cc" \
  "$plico_root/plico/tests/navigator_model_test.cc" \
  -o "$plico_root/build/tests/navigator_model_test"
"$plico_root/build/tests/navigator_model_test"
xcrun clang++ -std=c++20 -Wall -Wextra -Werror -pedantic -fno-exceptions \
  -fsanitize=address,undefined -g -I"$plico_root" \
  "$plico_root/plico/core/navigator_model.cc" \
  "$plico_root/plico/core/gesture_router.cc" \
  "$plico_root/plico/tests/gesture_router_test.cc" \
  -o "$plico_root/build/tests/gesture_router_test"
"$plico_root/build/tests/gesture_router_test"
