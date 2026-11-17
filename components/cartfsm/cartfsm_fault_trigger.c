#include "cartfsm_fault_trigger.h"
#ifdef CONFIG_CARTFSM_MT6835_FAULT_TRIGGER
#include "driver/gpio.h"
_Static_assert(GPIO_IS_VALID_OUTPUT_GPIO(CONFIG_CARTFSM_MT6835_FAULT_TRIGGER_GPIO),
               "MT6835 trigger requires an output-capable GPIO");
static bool latched;
esp_err_t cartfsm_fault_trigger_init(void)
{
    esp_err_t err = gpio_set_level(CONFIG_CARTFSM_MT6835_FAULT_TRIGGER_GPIO, 0);
    if (err != ESP_OK) return err;
    gpio_config_t pin = {.pin_bit_mask = UINT64_C(1) << CONFIG_CARTFSM_MT6835_FAULT_TRIGGER_GPIO, .mode = GPIO_MODE_OUTPUT,
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
        gpio_set_level(CONFIG_CARTFSM_MT6835_FAULT_TRIGGER_GPIO, 1);
    }
}
#endif
