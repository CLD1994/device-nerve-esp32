#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
for mode in on off; do
    : > "$tmp/sdkconfig.h"
    if [ "$mode" = on ]; then echo '#define CONFIG_BSP_POLE_ENC_SPI_DMA 1' > "$tmp/sdkconfig.h"; fi
    cc -std=gnu17 -Wall -Wextra -Werror -I"$tmp" -Ihost_tests/bsp_spi_stubs -Icomponents/bsp host_tests/bsp_spi_dma_test.c -o "$tmp/test"
    "$tmp/test"
done
echo 'SPI2 DMA invariant and SPI3 DMA on/off passed'
