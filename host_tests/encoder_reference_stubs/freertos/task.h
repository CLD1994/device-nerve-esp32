#pragma once
#include "FreeRTOS.h"
static inline TickType_t xTaskGetTickCount(void) {return 0;}
static inline void vTaskDelayUntil(TickType_t *p,TickType_t t) {(void)p;(void)t;}
void vTaskDelay(TickType_t t);
static inline BaseType_t xTaskCreatePinnedToCore(void (*fn)(void*),const char*n,int s,void*a,int p,void*h,int c){(void)fn;(void)n;(void)s;(void)a;(void)p;(void)h;(void)c;return pdPASS;}
