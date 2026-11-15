#pragma once
#include "esp_err.h"
typedef int gpio_num_t;
esp_err_t gpio_set_level(gpio_num_t pin,unsigned level);
esp_err_t gpio_input_enable(gpio_num_t pin);
int gpio_get_level(gpio_num_t pin);
