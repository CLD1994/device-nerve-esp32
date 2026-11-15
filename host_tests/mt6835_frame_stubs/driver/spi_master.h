#pragma once
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
typedef int spi_host_device_t;
typedef void *spi_device_handle_t;
typedef struct {int clock_speed_hz,mode,cs_ena_pretrans,spics_io_num,queue_size;} spi_device_interface_config_t;
typedef struct {int cmd,addr,length;const void *tx_buffer;void *rx_buffer;} spi_transaction_t;
esp_err_t spi_bus_add_device(spi_host_device_t,const spi_device_interface_config_t *,spi_device_handle_t *);
esp_err_t spi_device_polling_transmit(spi_device_handle_t,spi_transaction_t *);
