#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
${CC:-cc} -std=c11 -Wall -Wextra -Werror -Ihost_tests/stub \
  -Icomponents/settings/include host_tests/settings_startup_current_test.c \
  components/settings/startup_current.c -o "$tmp/settings_startup_current"
"$tmp/settings_startup_current"
