/*
 * poleang — 摆角解释组件（已标定摆角）
 *
 * 持有 magnetic_encoder 句柄，把原始角量解释为已标定摆角：
 * 零位与符号（POLE_ZERO_URAD / POLE_INV，来自 cartparams 注册表）
 * 在读取时应用。消费方读到的是标定后角度。
 * 语义：docs/superpowers/specs/2026-10-14-device-category-abstraction.md。
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "magnetic_encoder.h"

#ifdef __cplusplus
extern "C" {
#endif

/** 绑定编码器实例。 */
void poleang_init(magnetic_encoder_handle_t enc);

/** 已标定摆角（±π 环绕 µrad）；单圈角读取语义见 magnetic_encoder_angle_counts。
 * 首样本前使用缓存 0 换算，不代表有效机械角度。 */
int32_t poleang_theta_urad(void);

/** 已标定角速度（mrad/s，符号随 POLE_INV 翻转）；缓存值不携带有效性，不可用作停稳或安全判断。 */
int32_t poleang_vth_mrad_s(void);

typedef struct {
    int32_t theta_urad;
    int32_t vth_mrad_s;
    int64_t sampled_at_us;
    uint64_t sample_seq;
    int64_t velocity_span_us;
} poleang_measurement_t;
/** 同一编码器快照的角度和有效速度；无效返回false且不修改out。 */
bool poleang_get_measurement(poleang_measurement_t *out);

/** 连续 ≥10 次读取失败为 false；一次成功即恢复 true。 */
bool poleang_is_ok(void);

#ifdef __cplusplus
}
#endif
