#pragma once
#include <stdint.h>
#include "esp_err.h"
#define GPIO_IS_VALID_OUTPUT_GPIO(p) ((p)>=0 && (p)<=48 && !((p)>=22 && (p)<=25))
#define GPIO_MODE_OUTPUT 1
#define GPIO_PULLUP_DISABLE 0
#define GPIO_PULLDOWN_DISABLE 0
#define GPIO_INTR_DISABLE 0
typedef struct {uint64_t pin_bit_mask;int mode,pull_up_en,pull_down_en,intr_type;} gpio_config_t;
esp_err_t gpio_set_level(int pin,int level);
esp_err_t gpio_config(const gpio_config_t *config);
