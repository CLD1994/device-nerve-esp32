#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
common=(-std=gnu17 -Wall -Wextra -Werror -Ihost_tests/tmc_current_stubs -Ihost_tests/power_stubs -Ihost_tests/step_engine_stubs -Ihost_tests/stub -Icomponents/tmc2209/include -Icomponents/tmc2209)
cc "${common[@]}" host_tests/tmc_current_test.c components/tmc2209/tmc2209.c -lm -o "$tmp/current"
"$tmp/current"
cc "${common[@]}" host_tests/tmc_uart_test.c components/tmc2209/tmc2209_hw.c -o "$tmp/uart"
"$tmp/uart"
cc -std=gnu17 -Wall -Wextra -Werror -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub -Icomponents/cartcal/host_stub -Ihost_tests/stub $(find components -type d -name include -printf '-I%p ') host_tests/tmc_readonly_test.c components/cartfsm/cartfsm.c components/cartfsm/cartfsm_core.c components/cartparams/params.c components/cartproto/cartproto_parse.c -lm -o "$tmp/readonly"
"$tmp/readonly"
python -m unittest discover -s tools -p 'test_tmc_readonly.py'
