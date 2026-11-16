#pragma once
#include "sdkconfig.h"
#include "driver/spi_common.h"

/* 只改变摆杆总线的数据搬运方式；小车总线保持自动分配DMA。 */
static inline spi_dma_chan_t bsp_encoder_spi_dma(spi_host_device_t host)
{
#ifndef CONFIG_BSP_POLE_ENC_SPI_DMA
    if (host == SPI3_HOST) return SPI_DMA_DISABLED;
#else
    (void)host;
#endif
    return SPI_DMA_CH_AUTO;
}
