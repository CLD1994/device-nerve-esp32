idf_component_register(
    SRCS "settings.c" "startup_current.c"
    INCLUDE_DIRS "include"
    REQUIRES nvs_flash
)
