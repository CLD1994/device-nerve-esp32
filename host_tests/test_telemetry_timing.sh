#!/usr/bin/env bash
# 编译契约验证；不运行固件、不连接硬件。
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
for hz in 1000 2000; do
    "${CC:-cc}" -std=c11 -Wall -Wextra -Werror -DTEST_TICK_HZ="$hz" \
        -Icomponents/telemetry host_tests/telemetry_timing_test.c -o "$tmp/timing"
    "$tmp/timing"
done
for hz in 0 100 500 1024; do
    if "${CC:-cc}" -std=c11 -Wall -Wextra -Werror -DTEST_TICK_HZ="$hz" \
        -Icomponents/telemetry host_tests/telemetry_timing_test.c \
        -o "$tmp/timing" >"$tmp/error" 2>&1; then
        echo "ERROR: invalid tick rate $hz accepted" >&2
        exit 1
    fi
    grep -q 'telemetry requires ticks that exactly represent 1 ms' "$tmp/error"
done
echo 'telemetry timing: valid and invalid tick configurations passed'
