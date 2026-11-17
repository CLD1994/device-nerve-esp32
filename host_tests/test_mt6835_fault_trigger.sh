#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d);trap 'rm -rf "$tmp"' EXIT
includes=();while IFS= read -r p; do includes+=("-I$p"); done < <(find components -type d -name include)
for pin in 39 40; do
cc -DCONFIG_CARTFSM_MT6835_FAULT_TRIGGER_GPIO=$pin -std=c11 -Wall -Wextra -Werror -DCONFIG_CARTFSM_MT6835_FAULT_TRIGGER=1 \
 -Ihost_tests/fault_trigger_stubs -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub -Icomponents/cartcal/host_stub -Ihost_tests/stub "${includes[@]}" \
 host_tests/mt6835_fault_trigger_test.c host_tests/cartfsm_fixture.c components/cartfsm/cartfsm.c \
 components/cartfsm/cartfsm_fault_trigger.c components/cartfsm/cartfsm_diagnostics.c components/cartfsm/cartfsm_core.c components/cartparams/params.c -lm -o "$tmp/test"
for scenario in normal cart power init-fail; do "$tmp/test" "$scenario"; done

done
# ESP32-S3 GPIO22 is absent; reject the configuration before GPIO side effects.
if cc -std=c11 -Wall -Wextra -Werror -DCONFIG_CARTFSM_MT6835_FAULT_TRIGGER=1 \
 -DCONFIG_CARTFSM_MT6835_FAULT_TRIGGER_GPIO=22 -Ihost_tests/fault_trigger_stubs \
 -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub -Ihost_tests/stub "${includes[@]}" \
 -c components/cartfsm/cartfsm_fault_trigger.c -o "$tmp/invalid.o" 2>"$tmp/invalid.log"; then
 echo 'Invalid GPIO unexpectedly compiled' >&2; exit 1
fi
grep -q 'MT6835 trigger requires an output-capable GPIO' "$tmp/invalid.log"
