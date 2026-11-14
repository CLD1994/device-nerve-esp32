#pragma once
#include <stddef.h>
#include <stdint.h>
typedef int portMUX_TYPE;
typedef int BaseType_t;
typedef uint32_t TickType_t;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(l) do {(void)(l);}while(0)
#define portEXIT_CRITICAL(l) do {(void)(l);}while(0)
#define pdPASS 1
#define pdMS_TO_TICKS(ms) ((TickType_t)(ms))

#define pdTRUE 1
#define portMAX_DELAY UINT32_MAX
