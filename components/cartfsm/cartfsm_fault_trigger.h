#pragma once
#include "cartfsm.h"
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
#ifdef CONFIG_CARTFSM_MT6835_FAULT_TRIGGER
esp_err_t cartfsm_fault_trigger_init(void);
/* Only call after accepting a state transition and submitting protective stop. */
void cartfsm_fault_trigger_accepted(cm_reason_t reason);
#else
static inline esp_err_t cartfsm_fault_trigger_init(void) { return ESP_OK; }
static inline void cartfsm_fault_trigger_accepted(cm_reason_t reason) { (void)reason; }
#endif
