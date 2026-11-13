idf_component_register(
    SRCS "telemetry.c" "telemetry_format.c"
    INCLUDE_DIRS "include"
    REQUIRES cartpos poleang cartproto freertos
    PRIV_REQUIRES esp_timer
)
