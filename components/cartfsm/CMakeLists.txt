idf_component_register(
    SRCS "cartfsm.c" "cartfsm_core.c"
    INCLUDE_DIRS "include"
    PRIV_REQUIRES esp_timer
    REQUIRES cartcal settings cartpos poleang cartaxis cartparams cartproto cartpower freertos
)
