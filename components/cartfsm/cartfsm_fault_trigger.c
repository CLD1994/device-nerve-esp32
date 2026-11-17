#include "cartfsm_fault_trigger.h"
#ifdef CONFIG_CARTFSM_MT6835_FAULT_TRIGGER
#include "driver/gpio.h"
static bool latched;
esp_err_t cartfsm_fault_trigger_init(void)
{
    esp_err_t err = gpio_set_level(GPIO_NUM_39, 0);
    if (err != ESP_OK) return err;
    gpio_config_t pin = {.pin_bit_mask = UINT64_C(1) << 39, .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE, .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE};
    err = gpio_config(&pin);
    if (err == ESP_OK) latched = false;
    return err;
}
void cartfsm_fault_trigger_accepted(cm_reason_t reason)
{
    if (reason == CR_MT6835 && !latched) {
        latched = true;
        gpio_set_level(GPIO_NUM_39, 1);
    }
}
#endif
