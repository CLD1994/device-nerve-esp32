#pragma once
#include <stdint.h>
#include <stddef.h>
typedef int portMUX_TYPE;
typedef int BaseType_t;
typedef uint32_t TickType_t;
#define portMUX_INITIALIZER_UNLOCKED 0
#ifdef POWER_CRITICAL_HOOK
void power_test_enter(void);
#define portENTER_CRITICAL(l) do { (void)(l);power_test_enter(); } while(0)
#else
#define portENTER_CRITICAL(l) ((void)(l))
#endif
#define portEXIT_CRITICAL(l) ((void)(l))
#define pdMS_TO_TICKS(ms) (ms)
#define pdPASS 1
#define portMAX_DELAY UINT32_MAX
