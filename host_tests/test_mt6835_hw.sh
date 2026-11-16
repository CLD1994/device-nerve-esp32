#!/usr/bin/env bash
# 真实读帧实现配合SPI替身，不访问硬件。
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cc -std=c11 -Wall -Wextra -Werror -fsanitize=undefined \
  -Ihost_tests/mt6835_stubs -Ihost_tests/encoder_reference_stubs \
  -Icomponents/mt6835/include host_tests/mt6835_hw_test.c \
  components/mt6835/mt6835_hw.c components/mt6835/mt6835_urad.c \
  -o "$tmp/mt6835_hw"
"$tmp/mt6835_hw"
