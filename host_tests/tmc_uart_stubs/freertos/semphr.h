#pragma once
#include "freertos/FreeRTOS.h"
#include <assert.h>
#include <stdbool.h>
typedef void *SemaphoreHandle_t;
extern int power_test_lock_depth;
extern bool tmc_test_mutex_busy;
extern TickType_t tmc_test_mutex_wait;
extern unsigned tmc_test_mutex_calls;
static inline SemaphoreHandle_t xSemaphoreCreateMutex(void) { return (void*)1; }
static inline int xSemaphoreTake(SemaphoreHandle_t h,TickType_t t) {
    (void)h;
    tmc_test_mutex_wait=t;
    ++tmc_test_mutex_calls;
    if (tmc_test_mutex_busy) return 0;
    assert(power_test_lock_depth==0);power_test_lock_depth=1;return 1;
}
static inline int xSemaphoreGive(SemaphoreHandle_t h) {
    (void)h;assert(power_test_lock_depth==1);power_test_lock_depth=0;return 1;
}
