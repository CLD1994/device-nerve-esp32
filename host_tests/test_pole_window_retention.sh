#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d);trap 'rm -rf "$tmp"' EXIT
for diagnostic in off on; do
for rate in 1000 2000; do
 flags=();if [[ "$diagnostic" == on ]]; then flags+=(-DCONFIG_MAGNETIC_ENCODER_POLE_DIAGNOSTICS=1);fi
 if [[ "$rate" == 2000 ]]; then flags+=(-DCONFIG_MAGNETIC_ENCODER_SAMPLING_2KHZ=1);fi
 cc -std=gnu17 -Wall -Wextra -Werror "${flags[@]}" \
 -Ihost_tests/encoder_reference_stubs -Ihost_tests/stub -Icomponents/magnetic_encoder -Icomponents/magnetic_encoder/include \
 host_tests/pole_window_retention_test.c components/magnetic_encoder/magnetic_encoder_skeleton.c \
 components/magnetic_encoder/magnetic_encoder_tracker.c components/magnetic_encoder/magnetic_encoder_core.c -lm -o "$tmp/test"
 "$tmp/test"
done
done
