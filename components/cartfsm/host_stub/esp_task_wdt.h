#pragma once
#include "esp_err.h"
static inline esp_err_t esp_task_wdt_add(void *task) { (void)task; return ESP_OK; }
static inline void esp_task_wdt_reset(void) { }
