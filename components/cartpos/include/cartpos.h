/*
 * cartpos — 小车位置解释组件（编码器实测位置）
 *
 * 持有 magnetic_encoder 句柄，把原始 counts 解释为 mm 域小车位置：
 * 比例随每转行程（units_per_rev）订阅刷新，原点偏移存 µm 整数。
 * x_um = round(counts × 每转行程 × 1000 ÷ counts_per_rev) − 原点偏移。
 * 语义：docs/superpowers/specs/2026-10-14-device-category-abstraction.md。
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "magnetic_encoder.h"

#ifdef __cplusplus
extern "C" {
#endif

/** 绑定编码器实例并订阅每转行程（比例随变更刷新）。 */
void cartpos_init(magnetic_encoder_handle_t enc);

/** 连续位置（多圈、带符号、含回零原点偏移），µm 整数；首样本前为 0。 */
int64_t cartpos_position_um(void);

/** 缓存速度；不携带有效性，不可用作停稳或安全判断。 */
float cartpos_velocity_mm_s(void);

/* 监督证据：位置与编码器元数据来自同一次快照；不自行改变故障门限。 */
typedef struct {
    int64_t position_um;
    int32_t velocity_mm_s;
    magnetic_encoder_sample_t sample;
} cartpos_supervision_t;
bool cartpos_get_supervision(cartpos_supervision_t *out);

typedef struct { int32_t x_um; int32_t vx_mm_s; } cartpos_measurement_t;
/** 同一编码器快照的位置和有效速度；无效或越界返回false且不修改out。 */
bool cartpos_get_measurement(cartpos_measurement_t *out);
/* 连续性序列改变后本接口持续无效，直到重新成功 apply_reference。
 * 速度窗口重新预热不恢复丢失的多圈位置参考。 */

/** 连续 ≥10 次读取失败为 false；一次成功即恢复 true。 */
bool cartpos_is_ok(void);

/** 捕获的原始位置及其采样/比例版本；仅由 capture 填充，不持久化。 */
typedef struct {
    int64_t raw_um;
    uint64_t scale_revision;
    uint64_t failure_seq;
    uint64_t continuity_seq;
} cartpos_reference_t;

/**
 * DISABLED 下捕获稳定参考点，不产生运动、不修改原点。
 * 在任务上下文每 5 ms 检查：最近成功样本不超过按最高允许速度计算的连续性预算，最近读帧成功，
 * 成功序列持续推进、无读失败/长采样空窗，至少 100 ms 内位移范围≤100 µm。
 * 调用方不得持有自旋锁。失败不修改 out；调用方负责保证全程 DISABLED。
 */
bool cartpos_capture_reference(cartpos_reference_t *out);

/**
 * 按捕获时的位置定义 target_um，而非按调用时的位置重新采样定基。
 * 比例变更、采样连续性丢失或整数溢出时返回 false，原点不变。
 * 成功建立运行期参考有效性；调用方负责保证 DISABLED。
 */
bool cartpos_apply_reference(const cartpos_reference_t *ref, int64_t target_um);

/**
 * 检查当前参考采样连续性；失效后锁存为 false，直到下一次成功 apply。
 * 无参考、无成功样本、不新鲜、读失败、长采样空窗或比例变更均无效。
 */
bool cartpos_reference_is_valid(void);

/** 声明当前位置为 new_pos_mm（纯偏移建立，不产生运动）。 */
void cartpos_set_origin_mm(float new_pos_mm);

#ifdef __cplusplus
}
#endif
