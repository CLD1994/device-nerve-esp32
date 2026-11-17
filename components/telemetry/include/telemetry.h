/* 500Hz独立双lane快照；六字段十进制STATE，包括LF。 */
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
    int32_t position, velocity;
} telemetry_lane_t;
/** 创建组帧任务；固定500Hz发送最新快照。 */
esp_err_t telemetry_start(void);
/** 两lane独立校验age 0..20000us；失效lane仅输出数值0并清有效位。
 * 摆角position须在±3141592µrad内，否则仅摆杆lane失效。
 * now_us非负；成功返回实际字节数（含LF）；缓冲须额外容纳NUL。 */
int telemetry_format_state(char *buf,size_t len,int64_t now_us,
                           telemetry_lane_t cart,telemetry_lane_t pole);
#ifdef __cplusplus
}
#endif
