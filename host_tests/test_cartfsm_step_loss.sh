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
    host_tests/cartfsm_step_loss_diag_test.c host_tests/cartfsm_fixture.c components/cartfsm/cartfsm.c \
    components/cartfsm/cartfsm_core.c components/cartparams/params.c components/cartproto/cartproto_parse.c \
    -lm -o "$build/cartfsm-step-loss-test"
"$build/cartfsm-step-loss-test"

"${CC:-cc}" -std=c11 -Wall -Wextra -Werror \
    -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub \
    -Icomponents/cartcal/host_stub -Ihost_tests/stub "${includes[@]}" \
    host_tests/cartfsm_step_loss_disabled_test.c host_tests/cartfsm_fixture.c components/cartfsm/cartfsm.c \
    components/cartfsm/cartfsm_core.c components/cartparams/params.c components/cartproto/cartproto_parse.c \
    -lm -o "$build/cartfsm-step-loss-disabled-test"
"$build/cartfsm-step-loss-disabled-test"
