/*
 * telemetry_format — STATE 行组帧纯函数（无 ESP 依赖，宿主可测）
 */

#include "telemetry.h"

#include <stdio.h>

int telemetry_format_state(char *buf, size_t len, int32_t x_um,
                           int32_t theta_urad, int32_t vx_mm_s,
                           int32_t vth_mrad_s)
{
    if (buf == NULL || len < 40) {
        return -1;
    }
    int n = snprintf(buf, len, "STATE %ld %ld %ld %ld",
                     (long)x_um, (long)theta_urad,
                     (long)vx_mm_s, (long)vth_mrad_s);
    if (n < 0 || (size_t)n >= len) {
        return -1;
    }
    return n;
}


int telemetry_format_measurement(char *buf, size_t len, telemetry_validity_t *gate,
    int64_t now_us, bool cart_valid, bool pole_valid,
    int32_t x, int32_t theta, int32_t vx, int32_t vth)
{
    if (!buf || !gate || len == 0) return -1;
    bool report = !gate->initialized || gate->cart_valid != cart_valid
        || gate->pole_valid != pole_valid
        || now_us < gate->last_report_us || now_us - gate->last_report_us >= 100000;
    size_t used = 0;
    if (report) {
        int n = snprintf(buf, len, "VEL_VALID %d %d\n", cart_valid, pole_valid);
        if (n < 0 || (size_t)n >= len) return -1;
        used = (size_t)n;
    }
    if (cart_valid && pole_valid) {
        int n = telemetry_format_state(buf + used, len - used, x, theta, vx, vth);
        if (n < 0 || (size_t)n + 1 >= len - used) return -1;
        used += (size_t)n;
        buf[used++] = '\n'; buf[used] = '\0';
    }
    if (report) *gate = (telemetry_validity_t){true, cart_valid, pole_valid, now_us};
    return (int)used;
}
