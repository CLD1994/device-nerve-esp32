#pragma once
#include <stdbool.h>
#include "esp_err.h"
#include "driver/i2c_master.h"
/* 每次上电只请求一次20V；失败锁定到下一次重启。调用前必须禁用驱动。 */
esp_err_t cartpower_start(i2c_master_bus_handle_t bus);
/* 不访问I2C/ADC，不阻塞；同时检查缓存新鲜度。未初始化返回false。 */
bool cartpower_ready(void);
