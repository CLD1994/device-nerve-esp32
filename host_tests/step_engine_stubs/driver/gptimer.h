#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"
typedef void *gptimer_handle_t;
typedef struct {uint64_t alarm_value,count_value;} gptimer_alarm_event_data_t;
typedef struct {uint64_t alarm_count;struct {bool auto_reload_on_alarm;} flags;} gptimer_alarm_config_t;
typedef struct {int clk_src,direction;unsigned resolution_hz;} gptimer_config_t;
typedef struct {bool(*on_alarm)(gptimer_handle_t,const gptimer_alarm_event_data_t*,void*);} gptimer_event_callbacks_t;
#define GPTIMER_CLK_SRC_DEFAULT 0
#define GPTIMER_COUNT_UP 0
esp_err_t gptimer_stop(gptimer_handle_t t);
esp_err_t gptimer_start(gptimer_handle_t t);
esp_err_t gptimer_set_alarm_action(gptimer_handle_t t,const gptimer_alarm_config_t *a);
esp_err_t gptimer_new_timer(const gptimer_config_t *c, gptimer_handle_t *t);
esp_err_t gptimer_register_event_callbacks(gptimer_handle_t t, const gptimer_event_callbacks_t *c, void *a);
esp_err_t gptimer_enable(gptimer_handle_t t);
esp_err_t gptimer_get_raw_count(gptimer_handle_t t, uint64_t *v);
