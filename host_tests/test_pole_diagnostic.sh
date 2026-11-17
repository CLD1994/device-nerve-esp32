#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cc -std=c11 -Wall -Wextra -Werror -Icomponents/magnetic_encoder/include host_tests/pole_diagnostic_test.c -o "$tmp/core"
"$tmp/core"
cc -std=gnu17 -Wall -Wextra -Werror -DCONFIG_MAGNETIC_ENCODER_POLE_DIAGNOSTICS=1 \
 -Ihost_tests/encoder_reference_stubs -Ihost_tests/stub -Icomponents/magnetic_encoder -Icomponents/magnetic_encoder/include \
 host_tests/pole_diagnostic_sample_test.c components/magnetic_encoder/magnetic_encoder_skeleton.c \
 components/magnetic_encoder/magnetic_encoder_tracker.c components/magnetic_encoder/magnetic_encoder_core.c -lm -o "$tmp/sample"
"$tmp/sample"
includes=()
while IFS= read -r path; do includes+=("-I$path"); done < <(find components -type d -name include)
cc -DCONFIG_MAGNETIC_ENCODER_POLE_DIAGNOSTICS=1 -std=c11 -Wall -Wextra -Werror \
 -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub -Icomponents/cartcal/host_stub -Ihost_tests/stub "${includes[@]}" \
 host_tests/pole_diagnostic_query_test.c host_tests/cartfsm_fixture.c components/cartfsm/cartfsm.c \
 components/cartfsm/cartfsm_diagnostics.c components/cartfsm/cartfsm_core.c components/cartparams/params.c components/cartproto/cartproto_parse.c \
 -lm -o "$tmp/query"
"$tmp/query"
