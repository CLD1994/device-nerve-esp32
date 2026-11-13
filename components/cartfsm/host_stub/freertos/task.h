#pragma once
#include <stdint.h>
typedef int BaseType_t;
typedef uint32_t TickType_t;
#define pdPASS 1
#define pdMS_TO_TICKS(x) (x)
static inline TickType_t xTaskGetTickCount(void) { return 0; }
static inline void vTaskDelayUntil(TickType_t *last, TickType_t period) { (void)last; (void)period; }
static inline BaseType_t xTaskCreatePinnedToCore(void (*fn)(void *), const char *name, unsigned stack, void *arg, int prio, void *handle, int core)
{ (void)fn; (void)name; (void)stack; (void)arg; (void)prio; (void)handle; (void)core; return pdPASS; }
