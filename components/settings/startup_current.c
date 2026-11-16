#include "settings_startup_current.h"
#include "esp_log.h"

settings_status_t settings_apply_startup_run_current(bool enabled, int target_ma)
{
    if (!enabled) return SETTINGS_OK;
    const int old_run = settings_run_current_ma();
    const int hold = settings_hold_current_ma();
    ESP_LOGI("startup_current", "原有效运行请求=%d mA RMS，目标=%d mA RMS，保持请求=%d mA RMS",
             old_run, target_ma, hold);
    if (!settings_is_valid(SET_RUN_MA, (float)target_ma)) {
        ESP_LOGE("startup_current", "启动电流覆盖失败：INVALID；目标需满足参数范围且不低于保持请求，未写NVS");
        return SETTINGS_INVALID;
    }
    if (old_run == target_ma) {
        ESP_LOGI("startup_current", "有效运行请求已等于目标，无需写NVS；保持请求不变");
        return SETTINGS_OK;
    }
    settings_status_t status = settings_set(SET_RUN_MA, (float)target_ma);
    if (status != SETTINGS_OK) {
        ESP_LOGE("startup_current", "启动电流覆盖失败：%s（状态=%d），不继续设备初始化",
                 status == SETTINGS_STORAGE ? "STORAGE" : "INVALID", (int)status);
        return status;
    }
    ESP_LOGI("startup_current", "运行请求已持久化到NVS：%d mA RMS；保持请求仍为%d mA RMS；不是芯片回读或实测",
             target_ma, hold);
    return SETTINGS_OK;
}
