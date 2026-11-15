#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
build=$(mktemp -d)
trap 'rm -rf "$build"' EXIT
includes=()
while IFS= read -r path; do includes+=("-I$path"); done < <(find components -type d -name include)
"${CC:-cc}" -DCONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS=1 -std=c11 -Wall -Wextra -Werror \
    -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub \
    -Icomponents/cartcal/host_stub -Ihost_tests/stub "${includes[@]}" \
    host_tests/cartfsm_step_loss_diag_test.c host_tests/cartfsm_fixture.c components/cartfsm/cartfsm.c components/cartfsm/cartfsm_diagnostics.c \
    components/cartfsm/cartfsm_core.c components/cartparams/params.c components/cartproto/cartproto_parse.c \
    -lm -o "$build/cartfsm-step-loss-test"
"$build/cartfsm-step-loss-test"

"${CC:-cc}" -std=c11 -Wall -Wextra -Werror \
    -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub \
    -Icomponents/cartcal/host_stub -Ihost_tests/stub "${includes[@]}" \
    host_tests/cartfsm_step_loss_disabled_test.c host_tests/cartfsm_fixture.c components/cartfsm/cartfsm.c components/cartfsm/cartfsm_diagnostics.c \
    components/cartfsm/cartfsm_core.c components/cartparams/params.c components/cartproto/cartproto_parse.c \
    -lm -o "$build/cartfsm-step-loss-disabled-test"
"$build/cartfsm-step-loss-disabled-test"

for mode in events diag observe observe-diag; do
  flags=(-DCONFIG_CARTFSM_STEP_LOSS_EVENTS=1)
  case "$mode" in diag|observe-diag) flags+=(-DCONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS=1);; esac
  case "$mode" in observe|observe-diag) flags+=(-DCONFIG_CARTFSM_STEP_LOSS_OBSERVE_ONLY=1);; esac
  "${CC:-cc}" "${flags[@]}" -std=c11 -Wall -Wextra -Werror \
    -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub \
    -Icomponents/cartcal/host_stub -Ihost_tests/stub "${includes[@]}" \
    host_tests/cartfsm_step_loss_modes_test.c host_tests/cartfsm_fixture.c \
    components/cartfsm/cartfsm.c components/cartfsm/cartfsm_diagnostics.c \
    components/cartfsm/cartfsm_core.c components/cartparams/params.c components/cartproto/cartproto_parse.c \
    -lm -o "$build/$mode"
  "$build/$mode"
done

"${CC:-cc}" -std=c11 -Wall -Wextra -Werror host_tests/cartfsm_following_error_test.c -o "$build/window"
"$build/window"
for observe in 0 1; do
  flags=(-DCONFIG_CARTFSM_FOLLOWING_ERROR_WINDOW=1 -DCONFIG_CARTFSM_FOLLOWING_ERROR_HARD_UM=50000
    -DCONFIG_CARTFSM_FOLLOWING_ERROR_WINDOW_MS=50 -DCONFIG_CARTFSM_FOLLOWING_ERROR_GROWTH_UM=1000
    -DCONFIG_CARTFSM_FOLLOWING_ERROR_WINDOWS=2)
  if [ "$observe" = 1 ]; then flags+=(-DCONFIG_CARTFSM_STEP_LOSS_OBSERVE_ONLY=1); fi
  "${CC:-cc}" "${flags[@]}" -std=c11 -Wall -Wextra -Werror \
    -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub \
    -Icomponents/cartcal/host_stub -Ihost_tests/stub "${includes[@]}" \
    host_tests/cartfsm_window_mode_test.c host_tests/cartfsm_fixture.c \
    components/cartfsm/cartfsm.c components/cartfsm/cartfsm_diagnostics.c \
    components/cartfsm/cartfsm_core.c components/cartparams/params.c components/cartproto/cartproto_parse.c \
    -lm -o "$build/window-$observe"
  "$build/window-$observe"
done
