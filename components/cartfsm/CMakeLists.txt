idf_component_register(
    SRCS "cartfsm.c" "cartfsm_fault_trigger.c" "cartfsm_core.c" "cartfsm_diagnostics.c" "cartfsm_tmc_trace.c" "cartfsm_tmc_trace_core.c"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES esp_timer tmc2209 esp_driver_gpio
    REQUIRES cartcal settings cartpos poleang cartaxis cartparams cartproto cartpower freertos
)
