#!/usr/bin/env bash
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
cc -std=c11 -Wall -Wextra -Werror -I"$here/../firmware/main" \
  "$here/../firmware/main/probe_control.c" "$here/control_test.c" -o "$out/control-test"
"$out/control-test"
