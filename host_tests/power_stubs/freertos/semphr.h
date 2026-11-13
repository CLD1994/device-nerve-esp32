#pragma once
#include "FreeRTOS.h"
#include <assert.h>
typedef void *SemaphoreHandle_t;
extern int power_test_lock_depth;
static inline SemaphoreHandle_t xSemaphoreCreateMutex(void) { return (void*)1; }
static inline int xSemaphoreTake(SemaphoreHandle_t h,TickType_t t) {
    (void)h;(void)t;assert(power_test_lock_depth==0);power_test_lock_depth=1;return 1;
}
static inline int xSemaphoreGive(SemaphoreHandle_t h) {
    (void)h;assert(power_test_lock_depth==1);power_test_lock_depth=0;return 1;
}
