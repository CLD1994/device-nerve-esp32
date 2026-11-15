#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cc -std=c11 -Wall -Wextra -Werror -ffunction-sections -fdata-sections \
 -DCONFIG_MAGNETIC_ENCODER_FRAME_DIAGNOSTICS=1 \
 -Ihost_tests/mt6835_frame_stubs -Ihost_tests/encoder_reference_stubs -Ihost_tests/stub \
 -Icomponents/mt6835/include -Icomponents/magnetic_encoder/include \
 -Icomponents/magnetic_encoder \
 host_tests/mt6835_read_test.c components/mt6835/mt6835_hw.c components/mt6835/mt6835_urad.c \
 -Wl,--gc-sections -o "$tmp/test"
"$tmp/test"
