#pragma once
#include "FreeRTOS.h"
static inline TickType_t xTaskGetTickCount(void) {return 0;}
static inline void vTaskDelayUntil(TickType_t *p,TickType_t t) {(void)p;(void)t;}
void vTaskDelay(TickType_t t);
#ifdef ME_TIMER_TEST_CONTROLS
#include <setjmp.h>
extern jmp_buf me_task_wait_env;
extern int me_task_create_error, me_task_deletes, me_task_creates, me_run_task_before_return;
#endif
static inline BaseType_t xTaskCreatePinnedToCore(void (*fn)(void*),const char*n,int s,void*a,int p,void*h,int c){(void)fn;(void)n;(void)s;(void)a;(void)p;(void)h;(void)c;
#ifdef ME_TIMER_TEST_CONTROLS
 me_task_creates++;
 if (me_task_create_error) return 0;
 if (me_run_task_before_return && setjmp(me_task_wait_env)==0) fn(a);
#endif
 if(h) *(void**)h=(void*)2;
 return pdPASS;}

typedef void *TaskHandle_t;
static inline void xTaskNotifyGive(TaskHandle_t h) {(void)h;}
static inline uint32_t ulTaskNotifyTake(BaseType_t clear, TickType_t wait) {(void)clear;
#ifdef ME_TIMER_TEST_CONTROLS
 if (me_run_task_before_return && wait==portMAX_DELAY) longjmp(me_task_wait_env,1);
#endif
 (void)wait; return 0;}
static inline void vTaskDelete(TaskHandle_t h) {(void)h;
#ifdef ME_TIMER_TEST_CONTROLS
 me_task_deletes++;
#endif
}
