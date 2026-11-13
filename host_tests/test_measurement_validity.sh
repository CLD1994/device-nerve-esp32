#!/usr/bin/env bash
# 无硬件的解释层及遥测组帧单元测试；替身不访问真实串口。
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
gcc -std=c11 -Wall -Wextra -Werror \
  -Ihost_tests/encoder_reference_stubs -Ihost_tests/stub \
  -Icomponents/cartpos/include -Icomponents/poleang/include \
  -Icomponents/magnetic_encoder/include -Icomponents/cartparams/include -Icomponents/settings/include \
  host_tests/measurement_snapshot_test.c components/cartpos/cartpos.c components/poleang/poleang.c \
  -lm -o "$tmp/measurement"
"$tmp/measurement"
gcc -std=c11 -Wall -Wextra -Werror -Ihost_tests/stub -Icomponents/telemetry/include \
  host_tests/telemetry_validity_test.c components/telemetry/telemetry_format.c -o "$tmp/telemetry"
"$tmp/telemetry"
