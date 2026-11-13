#pragma once

#include <stdint.h>
#include "esp_err.h"

/* 只保存装置标定，不保存当前小车位置或使能状态。length_um=0 表示行程失效。 */
typedef struct {
    int32_t length_um;
    int32_t pole_zero_urad;
    int32_t pole_inv;
    float mm_per_rev;
} cartcal_record_t;

/* settings_init 已初始化 NVS。缺失返回 ESP_ERR_NVS_NOT_FOUND，非法记录返回
 * ESP_ERR_INVALID_STATE；其他存储错误透传。任何失败均不修改 out。 */
esp_err_t cartcal_load(cartcal_record_t *out);
/* 完整记录一次 set_blob + commit；只有 commit 成功才返回 ESP_OK。 */
esp_err_t cartcal_save(const cartcal_record_t *record);
