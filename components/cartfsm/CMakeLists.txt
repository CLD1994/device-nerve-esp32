idf_component_register(
    SRCS "cartfsm.c" "cartfsm_core.c"
    INCLUDE_DIRS "include"
    REQUIRES cartcal settings cartpos poleang cartaxis cartparams cartproto cartpower freertos
)
