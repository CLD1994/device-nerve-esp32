idf_component_register(SRCS "probe_main.c" "probe_control.c"
    INCLUDE_DIRS "."
    REQUIRES step_engine esp_driver_gpio esp_driver_uart esp_timer esp_system esp_app_format freertos)
