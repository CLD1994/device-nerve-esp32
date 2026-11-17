#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d);trap 'rm -rf "$tmp"' EXIT
cc -std=gnu17 -Wall -Wextra -Werror -DCONFIG_MAGNETIC_ENCODER_POLE_FAILURE_TRIGGER=1 \
 -Ihost_tests/encoder_reference_stubs -Ihost_tests/stub -Icomponents/magnetic_encoder -Icomponents/magnetic_encoder/include \
 host_tests/pole_failure_trigger_test.c components/magnetic_encoder/magnetic_encoder_skeleton.c \
 components/magnetic_encoder/magnetic_encoder_tracker.c components/magnetic_encoder/magnetic_encoder_core.c -lm -o "$tmp/trigger"
"$tmp/trigger"
