/*
 * poleang 将编码器单圈角度和速度换算为标定后的摆角。
 * 零位和方向来自运行参数；角度使用微弧度，速度使用毫弧度/秒。
 * get_measurement 从同一路编码器快照生成整组结果。
 */
#include "poleang.h"

#include <math.h>
#include <stddef.h>
#include <limits.h>

#include "magnetic_encoder.h"
#include "params.h"

/* floor(π × 1e6) / floor(2π × 1e6)，与 mt6835_urad 同约定 */
#define POLEANG_PI_URAD   3141592
#define POLEANG_2PI_URAD  6283185

static magnetic_encoder_handle_t s_enc;

void poleang_init(magnetic_encoder_handle_t enc)
{
    s_enc = enc;
}

int32_t poleang_theta_urad(void)
{
    const fw_params_t *p = fw_params();
    int32_t cpr = magnetic_encoder_counts_per_rev(s_enc);
    uint32_t raw = magnetic_encoder_angle_counts(s_enc);

    int64_t a = (int64_t)((uint64_t)raw * (uint64_t)POLEANG_2PI_URAD
                          / (uint64_t)cpr);
    a -= p->pole_zero_urad;

    while (a > POLEANG_PI_URAD) {
        a -= POLEANG_2PI_URAD;
    }
    while (a < -POLEANG_PI_URAD) {
        a += POLEANG_2PI_URAD;
    }

    return (p->pole_inv != 0) ? (int32_t)(-a) : (int32_t)a;
}

int32_t poleang_vth_mrad_s(void)
{
    const fw_params_t *p = fw_params();
    int32_t cpr = magnetic_encoder_counts_per_rev(s_enc);
    int32_t cps = magnetic_encoder_velocity_counts_per_s(s_enc);
    int32_t v = (int32_t)llround((double)cps * (double)POLEANG_2PI_URAD
                                 / (double)cpr / 1000.0);
    return (p->pole_inv != 0) ? -v : v;
}

bool poleang_is_ok(void)
{
    return magnetic_encoder_is_ok(s_enc);
}


bool poleang_get_measurement(poleang_measurement_t *out)
{
    magnetic_encoder_sample_t sample;
    if (out == NULL || !magnetic_encoder_get_sample(s_enc, &sample)
        || !sample.valid || !sample.ok || !sample.last_attempt_ok || !sample.velocity_valid) return false;
    int32_t cpr = magnetic_encoder_counts_per_rev(s_enc);
    if (cpr <= 0 || sample.raw_counts >= (uint32_t)cpr) return false;
    const fw_params_t *p = fw_params();
    int64_t angle = (int64_t)((uint64_t)sample.raw_counts * POLEANG_2PI_URAD / (uint64_t)cpr)
                    - p->pole_zero_urad;
    while (angle > POLEANG_PI_URAD) angle -= POLEANG_2PI_URAD;
    while (angle < -POLEANG_PI_URAD) angle += POLEANG_2PI_URAD;
    double v = (double)sample.velocity_counts_per_s * POLEANG_2PI_URAD / cpr / 1000.0;
    if (p->pole_inv) { angle = -angle; v = -v; }
    if (!isfinite(v) || v < INT32_MIN || v > INT32_MAX) return false;
    *out = (poleang_measurement_t){ .theta_urad = (int32_t)angle, .vth_mrad_s = (int32_t)llround(v),
        .sampled_at_us = sample.sampled_at_us, .sample_seq = sample.sample_seq,
        .velocity_span_us = sample.velocity_span_us };
    return true;
}
