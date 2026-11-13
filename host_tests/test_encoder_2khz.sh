#!/usr/bin/env bash
# 可选 2 kHz 调度策略、速度窗口与启动生命周期；不访问硬件。
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cc -std=c17 -Wall -Wextra -Werror \
  -DCONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ=1 \
  -Icomponents/magnetic_encoder host_tests/magnetic_encoder_sampling_test.c \
  -o "$tmp/policy"
"$tmp/policy"
for stats in off on; do
  flags=()
  if [[ $stats == on ]]; then flags+=(-DCONFIG_MAGNETIC_ENCODER_SAMPLING_STATS=1); fi
  cc -std=gnu17 -Wall -Wextra -Werror -fsanitize=undefined \
    -DCONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ=1 -DME_TIMER_TEST_CONTROLS=1 \
    "${flags[@]}" \
    -Ihost_tests/encoder_reference_stubs -Ihost_tests/stub \
    -Icomponents/magnetic_encoder -Icomponents/magnetic_encoder/include \
    host_tests/magnetic_encoder_2khz_test.c \
    components/magnetic_encoder/magnetic_encoder_skeleton.c \
    components/magnetic_encoder/magnetic_encoder_tracker.c \
    components/magnetic_encoder/magnetic_encoder_core.c -lm -o "$tmp/two_k_$stats"
  "$tmp/two_k_$stats"
done
