#pragma once
#include <stdbool.h>
#include "esp_err.h"
typedef void *pcnt_unit_handle_t;
typedef void *pcnt_channel_handle_t;
typedef struct { int low_limit,high_limit; struct { unsigned accum_count:1; } flags; } pcnt_unit_config_t;
typedef struct { int edge_gpio_num,level_gpio_num; } pcnt_chan_config_t;
typedef enum { PCNT_CHANNEL_EDGE_ACTION_HOLD, PCNT_CHANNEL_EDGE_ACTION_INCREASE } pcnt_channel_edge_action_t;
typedef enum { PCNT_CHANNEL_LEVEL_ACTION_KEEP, PCNT_CHANNEL_LEVEL_ACTION_INVERSE } pcnt_channel_level_action_t;
esp_err_t pcnt_new_unit(const pcnt_unit_config_t*,pcnt_unit_handle_t*);
esp_err_t pcnt_new_channel(pcnt_unit_handle_t,const pcnt_chan_config_t*,pcnt_channel_handle_t*);
esp_err_t pcnt_channel_set_edge_action(pcnt_channel_handle_t,pcnt_channel_edge_action_t,pcnt_channel_edge_action_t);
esp_err_t pcnt_channel_set_level_action(pcnt_channel_handle_t,pcnt_channel_level_action_t,pcnt_channel_level_action_t);
esp_err_t pcnt_unit_add_watch_point(pcnt_unit_handle_t,int);
esp_err_t pcnt_unit_clear_count(pcnt_unit_handle_t);
esp_err_t pcnt_unit_enable(pcnt_unit_handle_t);
esp_err_t pcnt_unit_disable(pcnt_unit_handle_t);
esp_err_t pcnt_unit_start(pcnt_unit_handle_t);
esp_err_t pcnt_unit_stop(pcnt_unit_handle_t);
esp_err_t pcnt_unit_get_count(pcnt_unit_handle_t,int*);
esp_err_t pcnt_del_channel(pcnt_channel_handle_t);
esp_err_t pcnt_del_unit(pcnt_unit_handle_t);
