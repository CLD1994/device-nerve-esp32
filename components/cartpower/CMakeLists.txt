idf_component_register(SRCS "cartpower.c" "cartpower_core.c"
                       INCLUDE_DIRS "include"
                       REQUIRES ch224q bsp esp_timer freertos)
