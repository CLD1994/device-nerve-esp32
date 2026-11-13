#pragma once
#include "esp_err.h"
typedef int gpio_num_t;
esp_err_t gpio_set_level(gpio_num_t pin,unsigned level);
