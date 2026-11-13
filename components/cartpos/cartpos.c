/*
 * cartpos — 小车位置解释实现
 *
 * 机械比例（每转行程 → µm/count）的唯一权威在本层：位置与速度同源
 * 同值。每转行程非法（≤0）回退 40 mm/rev 并告警。
 */
#include "cartpos.h"

#include <math.h>
#include <limits.h>
#include <inttypes.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "settings.h"

static const char *TAG = "cartpos";

#define CARTPOS_DEFAULT_UPR  40.0f  /* fallback if units_per_rev is unusable */

static magnetic_encoder_handle_t s_enc;
static double s_max_velocity_mm_s;

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static int64_t s_offset_um = 0;     /* 原点偏移（µm 整数） */
static double s_um_per_count = 0.0;
static uint64_t s_scale_revision;
static bool s_scale_valid;
static bool s_reference_valid;
static bool s_position_continuous;
static uint64_t s_position_sequence;
static cartpos_reference_t s_reference;

#define CARTPOS_REFERENCE_WINDOW_US 100000
#define CARTPOS_REFERENCE_RANGE_UM 100
#define CARTPOS_REFERENCE_POLL_MS 5

static void refresh_scale(void)
{
    float upr = settings_units_per_rev();
    bool valid = isfinite(upr) && upr > 0.0f;
    if (!valid) {
        ESP_LOGW(TAG, "invalid units_per_rev=%.3f — falling back to %.1f mm/rev",
                 (double)upr, (double)CARTPOS_DEFAULT_UPR);
        upr = CARTPOS_DEFAULT_UPR;
    }

    int32_t cpr = magnetic_encoder_counts_per_rev(s_enc);
    valid = valid && cpr > 0;
    double umc = cpr > 0 ? (double)upr * 1000.0 / (double)cpr : 0.0;

    /* 以装配层提供的最大速度预算，而不是当前运动命令。最多四分之一圈
     * 留出半圈解缠边界的裕量；这是工程策略，不是硬件实测上限。 */
    double vmax = s_max_velocity_mm_s;
    double budget = valid && isfinite(vmax) && vmax > 0 ? floor(
        floor(cpr / 4.0) * umc * 1000.0 / (double)vmax) : 0.0;
    int64_t gap = budget > MAGNETIC_ENCODER_MAX_CONTINUOUS_GAP_US
        ? MAGNETIC_ENCODER_MAX_CONTINUOUS_GAP_US : (int64_t)budget;
    valid = valid && gap > 0 && magnetic_encoder_set_continuous_gap_us(s_enc, gap);
    portENTER_CRITICAL(&s_lock);
    s_position_continuous = false;
    s_um_per_count = umc;
    s_scale_valid = valid;
    s_scale_revision++;
    s_reference_valid = false;
    portEXIT_CRITICAL(&s_lock);
}

/* Settings notification — only units_per_rev changes the counts → mm scale. */
static void on_settings_change(int idx, float new_value)
{
    (void)new_value;
    if (idx == SET_MM_PER_REV) {
        refresh_scale();
        ESP_LOGI(TAG, "units_per_rev changed — scale refreshed (%.6f µm/count)",
                 (double)settings_units_per_rev() * 1000.0
                     / (double)magnetic_encoder_counts_per_rev(s_enc));
    }
}

void cartpos_init(magnetic_encoder_handle_t enc, double max_velocity_mm_s)
{
    s_enc = enc;
    s_max_velocity_mm_s = max_velocity_mm_s;
    portENTER_CRITICAL(&s_lock);
    s_offset_um = 0;
    s_reference_valid = false;
    portEXIT_CRITICAL(&s_lock);
    refresh_scale();
    magnetic_encoder_sample_t initial;
    if (magnetic_encoder_get_sample(s_enc, &initial)) {
        portENTER_CRITICAL(&s_lock);
        s_position_sequence = initial.continuity_seq;
        s_position_continuous = s_scale_valid;
        portEXIT_CRITICAL(&s_lock);
    }
    if (!settings_subscribe(on_settings_change)) {
        ESP_LOGW(TAG, "settings 订阅失败（槽满）——每转行程变更不会生效");
    }
}

/* 无偏移原始位置（µm） */
static int64_t raw_um(int64_t counts)
{
    double umc;
    portENTER_CRITICAL(&s_lock);
    umc = s_um_per_count;
    portEXIT_CRITICAL(&s_lock);
    return (int64_t)llround((double)counts * umc);
}

int64_t cartpos_position_um(void)
{
    portENTER_CRITICAL(&s_lock);
    int64_t offset = s_offset_um;
    portEXIT_CRITICAL(&s_lock);
    return raw_um(magnetic_encoder_position_counts(s_enc)) - offset;
}

float cartpos_velocity_mm_s(void)
{
    double umc;
    portENTER_CRITICAL(&s_lock);
    umc = s_um_per_count;
    portEXIT_CRITICAL(&s_lock);
    return (float)((double)magnetic_encoder_velocity_counts_per_s(s_enc)
                   * umc / 1000.0);
}

bool cartpos_is_ok(void)
{
    return magnetic_encoder_is_ok(s_enc);
}

void cartpos_set_origin_mm(float new_pos_mm)
{
    int64_t raw = raw_um(magnetic_encoder_position_counts(s_enc));
    int64_t offset = raw - (int64_t)llround((double)new_pos_mm * 1000.0);

    portENTER_CRITICAL(&s_lock);
    s_offset_um = offset;
    s_reference_valid = false;
    portEXIT_CRITICAL(&s_lock);

    ESP_LOGI(TAG, "原点已重置：%.3f mm（原始 %.3f mm，偏移 %" PRId64 " µm）",
             (double)new_pos_mm, (double)raw / 1000.0, offset);
}

/* 不以旧的 is_ok=true 或零速度推断已有有效、连续的新样本。 */
static bool fresh_sample(magnetic_encoder_sample_t *sample)
{
    if (!magnetic_encoder_get_sample(s_enc, sample)) {
        return false;
    }
    int64_t now = esp_timer_get_time();
    return sample->valid && sample->ok && sample->last_attempt_ok
        && sample->sampled_at_us >= 0 && sample->sampled_at_us <= now
        && sample->continuous_gap_us > 0
        && now - sample->sampled_at_us <= sample->continuous_gap_us;
}

static bool checked_raw_um(int64_t counts, double scale, int64_t *out)
{
    double value = (double)counts * scale;
    /* double 的 INT64_MAX 向上舍入为 2^63；必须排除该边界。 */
    if (!isfinite(value) || value >= 0x1p63 || value < -0x1p63) {
        return false;
    }
    *out = (int64_t)llround(value);
    return true;
}

bool cartpos_capture_reference(cartpos_reference_t *out)
{
    if (out == NULL || s_enc == NULL) {
        return false;
    }
    double scale;
    uint64_t revision;
    bool scale_valid;
    portENTER_CRITICAL(&s_lock);
    scale = s_um_per_count;
    revision = s_scale_revision;
    scale_valid = s_scale_valid;
    portEXIT_CRITICAL(&s_lock);
    if (!scale_valid) {
        return false;
    }

    magnetic_encoder_sample_t first;
    int64_t min_um, max_um;
    if (!fresh_sample(&first) || !checked_raw_um(first.position_counts, scale, &min_um)) {
        return false;
    }
    max_um = min_um;
    uint64_t previous_seq = first.sample_seq;
    int64_t start = esp_timer_get_time();
    int64_t last_check = start;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(CARTPOS_REFERENCE_POLL_MS) > 0
                       ? pdMS_TO_TICKS(CARTPOS_REFERENCE_POLL_MS) : 1);
        int64_t now = esp_timer_get_time();
        if (now - last_check > MAGNETIC_ENCODER_MAX_CONTINUOUS_GAP_US) {
            return false;
        }
        last_check = now;
        magnetic_encoder_sample_t current;
        int64_t raw;
        if (!fresh_sample(&current) || current.sample_seq <= previous_seq
            || current.failure_seq != first.failure_seq
            || current.continuity_seq != first.continuity_seq
            || current.sampled_at_us < first.sampled_at_us
            || !checked_raw_um(current.position_counts, scale, &raw)) {
            return false;
        }
        previous_seq = current.sample_seq;
        if (raw < min_um) min_um = raw;
        if (raw > max_um) max_um = raw;
        if ((uint64_t)max_um - (uint64_t)min_um > CARTPOS_REFERENCE_RANGE_UM) {
            return false;
        }
        portENTER_CRITICAL(&s_lock);
        bool same_scale = s_scale_valid && s_scale_revision == revision;
        portEXIT_CRITICAL(&s_lock);
        if (!same_scale) {
            return false;
        }
        if (now - start >= CARTPOS_REFERENCE_WINDOW_US
            && current.sampled_at_us - first.sampled_at_us >= CARTPOS_REFERENCE_WINDOW_US) {
            *out = (cartpos_reference_t){
                .raw_um = raw, .scale_revision = revision,
                .failure_seq = current.failure_seq,
                .continuity_seq = current.continuity_seq,
            };
            return true;
        }
        /* 采样时间未推进足够长时，不能无限等待。 */
        if (esp_timer_get_time() - start > CARTPOS_REFERENCE_WINDOW_US
                                          + MAGNETIC_ENCODER_MAX_CONTINUOUS_GAP_US) {
            return false;
        }
    }
}

bool cartpos_apply_reference(const cartpos_reference_t *ref, int64_t target_um)
{
    magnetic_encoder_sample_t current;
    if (ref == NULL || !fresh_sample(&current)
        || current.failure_seq != ref->failure_seq
        || current.continuity_seq != ref->continuity_seq
        || (target_um > 0 && ref->raw_um < INT64_MIN + target_um)
        || (target_um < 0 && ref->raw_um > INT64_MAX + target_um)) {
        return false;
    }
    portENTER_CRITICAL(&s_lock);
    /* 与本层比例/参考提交串行，再核对编码器序列。gap 若在这次原子
     * 快照之后发生，由下一次 reference/measurement 检查拒绝，不会
     * 因为本次重新定位而清除编码器的连续性历史。 */
    bool accepted = s_scale_valid && s_scale_revision == ref->scale_revision
        && fresh_sample(&current)
        && current.failure_seq == ref->failure_seq
        && current.continuity_seq == ref->continuity_seq;
    if (accepted) {
        s_offset_um = ref->raw_um - target_um;
        s_position_sequence = ref->continuity_seq;
        s_position_continuous = true;
        s_reference = *ref;
        s_reference_valid = true;
    }
    portEXIT_CRITICAL(&s_lock);
    return accepted;
}

bool cartpos_reference_is_valid(void)
{
    magnetic_encoder_sample_t current;
    portENTER_CRITICAL(&s_lock);
    bool fresh = fresh_sample(&current);
    if (s_reference_valid && (!fresh || !s_scale_valid
        || s_scale_revision != s_reference.scale_revision
        || current.failure_seq != s_reference.failure_seq
        || current.continuity_seq != s_reference.continuity_seq)) {
        s_reference_valid = false;
    }
    bool valid = s_reference_valid;
    portEXIT_CRITICAL(&s_lock);
    return valid;
}


bool cartpos_get_measurement(cartpos_measurement_t *out)
{
    magnetic_encoder_sample_t sample;
    if (out == NULL || !fresh_sample(&sample) || !sample.velocity_valid) return false;
    portENTER_CRITICAL(&s_lock);
    double scale = s_um_per_count;
    int64_t offset = s_offset_um;
    /* 旧的只读快照不能把并发刚建立的新参考永久置无效。序列本身
     * 单调递增，未重新定位时不可能重新匹配。 */
    bool valid = s_scale_valid && s_position_continuous
        && sample.continuity_seq == s_position_sequence;
    portEXIT_CRITICAL(&s_lock);
    double x = (double)sample.position_counts * scale - (double)offset;
    double v = (double)sample.velocity_counts_per_s * scale / 1000.0;
    if (!valid || !isfinite(x) || !isfinite(v)
        || x < INT32_MIN || x > INT32_MAX || v < INT32_MIN || v > INT32_MAX) return false;
    *out = (cartpos_measurement_t){ .x_um = (int32_t)llround(x), .vx_mm_s = (int32_t)llround(v),
        .sampled_at_us = sample.sampled_at_us, .sample_seq = sample.sample_seq,
        .velocity_span_us = sample.velocity_span_us };
    return true;
}
