#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
build=$(mktemp -d)
trap 'rm -rf "$build"' EXIT
includes=()
while IFS= read -r path; do includes+=("-I$path"); done < <(find components -type d -name include)
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror \
    -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub \
    -Icomponents/cartcal/host_stub -Ihost_tests/stub "${includes[@]}" \
    host_tests/cartfsm_calibration_test.c host_tests/cartfsm_fixture.c components/cartfsm/cartfsm.c \
    components/cartfsm/cartfsm_core.c components/cartparams/params.c \
    -lm -o "$build/cartfsm-calibration-test"
# 单例的三个上电存储场景各自运行；测试进程内只有注入的内存协作者。
for scenario in missing invalid valid; do
    "$build/cartfsm-calibration-test" "$scenario"
done
