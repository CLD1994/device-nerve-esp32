#pragma once
#include <stddef.h>
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#define pdTRUE 1
#define UART_DATA_8_BITS 8
#define UART_PARITY_DISABLE 0
#define UART_STOP_BITS_1 1
#define UART_HW_FLOWCTRL_DISABLE 0
#define UART_SCLK_DEFAULT 0
#define UART_PIN_NO_CHANGE -1
typedef struct { int baud_rate,data_bits,parity,stop_bits,flow_ctrl,source_clk; } uart_config_t;
esp_err_t uart_flush_input(int);
int uart_write_bytes(int,const void*,size_t);
esp_err_t uart_wait_tx_done(int,TickType_t);
int uart_read_bytes(int,void*,uint32_t,TickType_t);
esp_err_t uart_driver_install(int,int,int,int,void*,int);
esp_err_t uart_param_config(int,const uart_config_t*);
esp_err_t uart_set_pin(int,int,int,int,int);
