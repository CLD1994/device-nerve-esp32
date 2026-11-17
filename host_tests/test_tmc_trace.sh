#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
build=$(mktemp -d);trap 'rm -rf "$build"' EXIT
flags=(-std=c11 -Wall -Wextra -Werror)
cc "${flags[@]}" host_tests/cartfsm_tmc_trace_core_test.c components/cartfsm/cartfsm_tmc_trace_core.c -o "$build/core"
"$build/core"
cc "${flags[@]}" -DCONFIG_CARTFSM_TMC_TRACE=1 -Ihost_tests/power_stubs -Ihost_tests/stub -Icomponents/tmc2209/include -Icomponents/cartproto/include -Icomponents/cartfsm/include -Icomponents/cartparams/include host_tests/cartfsm_tmc_trace_runtime_test.c components/cartfsm/cartfsm_tmc_trace.c components/cartfsm/cartfsm_tmc_trace_core.c -o "$build/runtime"
"$build/runtime"
includes=();while IFS= read -r p;do includes+=("-I$p");done < <(find components -type d -name include)
for enabled in 0 1; do
  config=();if [ "$enabled" = 1 ];then config+=(-DCONFIG_CARTFSM_TMC_TRACE=1);fi
  cc "${flags[@]}" "${config[@]}" -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub -Icomponents/cartcal/host_stub -Ihost_tests/stub "${includes[@]}" host_tests/cartfsm_tmc_trace_gate_test.c host_tests/cartfsm_fixture.c components/cartfsm/cartfsm.c components/cartfsm/cartfsm_diagnostics.c components/cartfsm/cartfsm_core.c components/cartparams/params.c components/cartproto/cartproto_parse.c -lm -o "$build/gate-$enabled"
  "$build/gate-$enabled"
done
