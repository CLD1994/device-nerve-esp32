#pragma once
#include "FreeRTOS.h"
BaseType_t xTaskCreate(void (*fn)(void*),const char*,unsigned,void*,unsigned,void*);
BaseType_t xTaskCreatePinnedToCore(void (*fn)(void*),const char*,unsigned,void*,unsigned,void*,unsigned);
void vTaskDelay(TickType_t);
void vTaskDelayUntil(TickType_t*,TickType_t);
TickType_t xTaskGetTickCount(void);
void vTaskDelete(void*);
