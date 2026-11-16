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

# Compile the task as well as the pure formatting/timing helpers.
includes=()
while IFS= read -r path; do includes+=("-I$path"); done < <(find components -type d -name include)
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -DconfigTICK_RATE_HZ=1000 \
  -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub -Ihost_tests/stub \
  "${includes[@]}" -fsyntax-only components/telemetry/telemetry.c

# 独立小车流默认关闭/启用：固定限流，无边沿突发。
for mode in off on; do
  flags=()
  if [[ $mode == on ]]; then flags+=(-DCONFIG_TELEMETRY_CART_DIAGNOSTICS=1); fi
  "${CC:-cc}" -std=c11 -Wall -Wextra -Werror "${flags[@]}" \
    -Ihost_tests/stub -Icomponents/telemetry/include \
    host_tests/telemetry_cart_test.c components/telemetry/telemetry_cart_format.c -o "$tmp/cart-$mode"
  "$tmp/cart-$mode"
  "${CC:-cc}" -std=c11 -Wall -Wextra -Werror -DconfigTICK_RATE_HZ=1000 "${flags[@]}" \
    -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub -Ihost_tests/stub \
    "${includes[@]}" -fsyntax-only components/telemetry/telemetry.c
done
