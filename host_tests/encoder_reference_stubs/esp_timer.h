#pragma once
#include <stdint.h>
#include <stdbool.h>
int64_t esp_timer_get_time(void);

#include "esp_err.h"
typedef void *esp_timer_handle_t;
#define ESP_TIMER_TASK 0
typedef struct {
    void (*callback)(void *); void *arg; int dispatch_method;
    const char *name; bool skip_unhandled_events;
} esp_timer_create_args_t;
#ifdef ME_TIMER_TEST_CONTROLS
extern int me_timer_create_error, me_timer_start_error, me_timer_deletes;
#endif
static inline esp_err_t esp_timer_create(const esp_timer_create_args_t *a, esp_timer_handle_t *h)
{(void)a;
#ifdef ME_TIMER_TEST_CONTROLS
 if (me_timer_create_error) return me_timer_create_error;
#endif
 *h=(void*)1;return ESP_OK;}
static inline esp_err_t esp_timer_start_periodic(esp_timer_handle_t h, uint64_t period)
{(void)h;(void)period;
#ifdef ME_TIMER_TEST_CONTROLS
 return me_timer_start_error;
#else
 return ESP_OK;
#endif
}
static inline esp_err_t esp_timer_delete(esp_timer_handle_t h)
{(void)h;
#ifdef ME_TIMER_TEST_CONTROLS
 me_timer_deletes++;
#endif
 return ESP_OK;}
