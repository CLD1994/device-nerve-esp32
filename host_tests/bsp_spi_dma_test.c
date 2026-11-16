#include <assert.h>
#include "bsp_spi_dma.h"
int main(void)
{
    assert(bsp_encoder_spi_dma(SPI2_HOST)==SPI_DMA_CH_AUTO);
#ifdef CONFIG_BSP_POLE_ENC_SPI_DMA
    assert(bsp_encoder_spi_dma(SPI3_HOST)==SPI_DMA_CH_AUTO);
#else
    assert(bsp_encoder_spi_dma(SPI3_HOST)==SPI_DMA_DISABLED);
#endif
    return 0;
}
