/* 500Hz独立双lane快照；固定82字节十六进制STATE，包括LF。 */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
    bool valid;
    int64_t sampled_at_us;
    uint64_t sample_seq;
    int32_t position, velocity;
} telemetry_lane_t;
/** 创建组帧任务；每次启动生成独立32位随机boot标记，允许0。 */
esp_err_t telemetry_start(void);
/** 两lane独立校验age 0..20000us；失效lane规范化seq0/ageffff/数值0。
 * 摆角position须在±3141592µrad内，否则仅摆杆lane失效。
 * now_us非负；成功返回82（含LF），需要至少83字节含NUL。 */
int telemetry_format_state(char *buf,size_t len,uint32_t boot,int64_t now_us,
                           telemetry_lane_t cart,telemetry_lane_t pole);
#ifdef __cplusplus
}
#endif
