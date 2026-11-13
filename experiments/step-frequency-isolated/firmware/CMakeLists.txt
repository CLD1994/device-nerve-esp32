cmake_minimum_required(VERSION 3.16)
set(IDF_TARGET "esp32s3")
set(SDKCONFIG_DEFAULTS "${CMAKE_CURRENT_LIST_DIR}/../../../sdkconfig.defaults;${CMAKE_CURRENT_LIST_DIR}/sdkconfig.defaults")
# Compile the real production source; do not replace it with a benchmark ISR.
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../../../components/step_engine")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
idf_build_set_property(MINIMAL_BUILD ON)
project(cartpole-step-isolated)
