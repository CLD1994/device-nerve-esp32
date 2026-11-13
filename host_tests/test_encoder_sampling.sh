#!/usr/bin/env bash
# 编码器采样服务和时间窗口单元测试；不启动硬件任务。
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cc -std=gnu17 -Wall -Wextra -Werror \
  -Ihost_tests/encoder_reference_stubs -Ihost_tests/stub \
  -Icomponents/magnetic_encoder -Icomponents/magnetic_encoder/include \
  host_tests/magnetic_encoder_sample_test.c \
  components/magnetic_encoder/magnetic_encoder_skeleton.c \
  components/magnetic_encoder/magnetic_encoder_tracker.c \
  components/magnetic_encoder/magnetic_encoder_core.c -lm -o "$tmp/sample"
"$tmp/sample"
for test in magnetic_encoder_core_test magnetic_encoder_timed_velocity_test; do
  cc -std=c11 -Wall -Wextra -Werror -Icomponents/magnetic_encoder \
    "host_tests/${test}.c" components/magnetic_encoder/magnetic_encoder_core.c \
    -lm -o "$tmp/$test"
  "$tmp/$test"
done
