#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d);trap 'rm -rf "$tmp"' EXIT
includes=();while IFS= read -r p; do includes+=("-I$p"); done < <(find components -type d -name include)
cc -std=c11 -Wall -Wextra -Werror -DCONFIG_CARTFSM_MT6835_FAULT_TRIGGER=1 \
 -Ihost_tests/fault_trigger_stubs -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub -Icomponents/cartcal/host_stub -Ihost_tests/stub "${includes[@]}" \
 host_tests/mt6835_fault_trigger_test.c host_tests/cartfsm_fixture.c components/cartfsm/cartfsm.c \
 components/cartfsm/cartfsm_fault_trigger.c components/cartfsm/cartfsm_diagnostics.c components/cartfsm/cartfsm_core.c components/cartparams/params.c -lm -o "$tmp/test"
for scenario in normal cart power init-fail; do "$tmp/test" "$scenario"; done
