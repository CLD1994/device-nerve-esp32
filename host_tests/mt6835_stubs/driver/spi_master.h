#pragma once
/* 仅覆盖 MT6835 读帧实现使用的 ESP-IDF SPI 接口；不模拟硬件时序。 */
#include <stdint.h>
#include "esp_err.h"
typedef int spi_host_device_t;
typedef void *spi_device_handle_t;
typedef struct {
    int clock_speed_hz, mode, cs_ena_pretrans, spics_io_num, queue_size;
} spi_device_interface_config_t;
typedef struct {
    int cmd, addr, length;
    const void *tx_buffer;
    void *rx_buffer;
} spi_transaction_t;
esp_err_t spi_bus_add_device(spi_host_device_t host,
    const spi_device_interface_config_t *cfg, spi_device_handle_t *out);
esp_err_t spi_device_polling_transmit(spi_device_handle_t dev, spi_transaction_t *t);
