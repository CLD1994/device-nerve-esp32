#pragma once
#include "esp_err.h"
#ifdef ME_TIMER_TEST_CONTROLS
extern int me_wdt_adds;
#endif
static inline esp_err_t esp_task_wdt_add(void *p) {(void)p;
#ifdef ME_TIMER_TEST_CONTROLS
 me_wdt_adds++;
#endif
 return ESP_OK;}
static inline void esp_task_wdt_reset(void) {}
