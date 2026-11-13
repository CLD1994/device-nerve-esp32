/*
 * magnetic_encoder_skeleton — 采样骨架（类别组件内部）
 *
 * 收编自两实现的原各自副本：1 kHz 采样任务（CPU1、优先级 3，
 * 阻塞总线事务不扰 CPU0 的 STEP ISR）、失败计数（≥10 次 NOT OK，
 * 纯函数见 magnetic_encoder_core.c）、16 样本速度窗、s_lock 内
 * 原子发布。实例全部状态进 magnetic_encoder_inst_t（arg=实例）。
 *
 * 层内约束：不 include settings.h；不调用 bsp；总线交互只经
 * impl->read_frame 回调。
 */

#include "magnetic_encoder_impl.h"

#include <stdio.h>
#include <string.h>

#include "freertos/task.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"

/* ---- 任务布局（契约不变量：CPU1、优先级 3、1 kHz） ---- */
#define ME_SKELETON_PERIOD_MS   1
#define ME_SKELETON_TASK_PRIO   3
#define ME_SKELETON_TASK_CORE   1
#define ME_SKELETON_TASK_STACK  3072

/* ================================================================
 * 状态发布（仅采样任务调用；首读时任务未起，同样安全）
 * ================================================================ */

static bool publish_sample(magnetic_encoder_inst_t *inst,
                           uint32_t raw, uint8_t status)
{
    int64_t now_us = esp_timer_get_time();
    portENTER_CRITICAL(&inst->lock);
    bool recovered = magnetic_encoder_fail_step(&inst->fail, true);

    /* 多圈累计（首样本种子）+ 速度窗推进，一并原子发布 */
    int64_t pos = magnetic_encoder_tracker_update(
        &inst->tracker, raw, inst->impl->counts_per_rev(inst->impl_ctx));
    inst->pos_counts      = pos;
    inst->last_raw        = raw;
    inst->status          = status;
    if (inst->has_sample &&
        (now_us <= inst->sampled_at_us ||
         now_us - inst->sampled_at_us > MAGNETIC_ENCODER_MAX_CONTINUOUS_GAP_US)) {
        inst->continuity_seq++;
    }
    magnetic_encoder_velocity_t velocity = magnetic_encoder_vel_push_at(
        &inst->vel, pos, now_us, MAGNETIC_ENCODER_MAX_CONTINUOUS_GAP_US);
    inst->velocity_valid = velocity.valid;
    inst->velocity_span_us = velocity.span_us;
    if (velocity.valid) inst->vel_counts_per_s = velocity.counts_per_s;
    inst->sampled_at_us = now_us;
    inst->sample_seq++;
    inst->has_sample = true;
    inst->last_attempt_ok = true;

    portEXIT_CRITICAL(&inst->lock);
    return recovered;
}

/* 失败计数推进（与契约 is_ok 读同锁，保证 NOT OK 可见性同步） */
static bool fail_step_locked(magnetic_encoder_inst_t *inst, bool read_ok)
{
    portENTER_CRITICAL(&inst->lock);
    bool event = magnetic_encoder_fail_step(&inst->fail, read_ok);
    inst->last_attempt_ok = read_ok;
    if (!read_ok) {
        inst->failure_seq++;
        magnetic_encoder_vel_win_reset(&inst->vel);
        inst->velocity_valid = false;
        inst->velocity_span_us = 0;
    }
    portEXIT_CRITICAL(&inst->lock);
    return event;
}

static void fail_desc_of(const magnetic_encoder_inst_t *inst,
                         char *buf, size_t len)
{
    if (inst->impl->fail_desc != NULL) {
        inst->impl->fail_desc(inst->impl_ctx, buf, len);
        return;
    }
    snprintf(buf, len, "读取失败");
}

/* ================================================================
 * 采样任务（1 kHz，CPU1）
 * ================================================================ */

static void skeleton_task(void *arg)
{
    magnetic_encoder_inst_t *inst = (magnetic_encoder_inst_t *)arg;

    TickType_t last_wake = xTaskGetTickCount();

    bool wdt_ok = (esp_task_wdt_add(NULL) == ESP_OK);
    if (!wdt_ok) {
        ESP_LOGW(inst->name, "任务看门狗订阅失败——采样任务不受监控");
    }

    while (1) {
        uint32_t raw = 0;
        uint8_t status = 0;

        if (inst->impl->read_frame(inst->impl_ctx, &raw, &status)) {
            if (publish_sample(inst, raw, status)) {
                ESP_LOGI(inst->name, "读取在连续 %d 次失败后恢复",
                         MAGNETIC_ENCODER_FAIL_LIMIT);
            }

            if (inst->impl->on_sample != NULL) {
                inst->impl->on_sample(inst->impl_ctx, status);
            }
        } else {
            if (fail_step_locked(inst, false)) {
                char desc[96];
                fail_desc_of(inst, desc, sizeof(desc));
                ESP_LOGE(inst->name,
                         "连续 %d 次读取失败——编码器标记 NOT OK（%s）",
                         MAGNETIC_ENCODER_FAIL_LIMIT, desc);
            }
        }

        if (wdt_ok) {
            esp_task_wdt_reset();
        }

        /* Fixed 1 kHz cadence; never busy-wait (watchdog). */
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(ME_SKELETON_PERIOD_MS));
    }
}

/* ================================================================
 * 契约操作表的骨架公共实现
 * ================================================================ */

int32_t magnetic_encoder_inst_counts_per_rev(magnetic_encoder_handle_t enc)
{
    magnetic_encoder_inst_t *inst = (magnetic_encoder_inst_t *)enc;
    return inst->impl->counts_per_rev(inst->impl_ctx);
}

uint32_t magnetic_encoder_inst_angle_counts(magnetic_encoder_handle_t enc)
{
    magnetic_encoder_inst_t *inst = (magnetic_encoder_inst_t *)enc;
    portENTER_CRITICAL(&inst->lock);
    uint32_t raw = inst->last_raw;
    portEXIT_CRITICAL(&inst->lock);
    return raw;
}

int64_t magnetic_encoder_inst_position_counts(magnetic_encoder_handle_t enc)
{
    magnetic_encoder_inst_t *inst = (magnetic_encoder_inst_t *)enc;
    portENTER_CRITICAL(&inst->lock);
    int64_t p = inst->pos_counts;
    portEXIT_CRITICAL(&inst->lock);
    return p;
}

int32_t magnetic_encoder_inst_velocity_counts_per_s(magnetic_encoder_handle_t enc)
{
    magnetic_encoder_inst_t *inst = (magnetic_encoder_inst_t *)enc;
    portENTER_CRITICAL(&inst->lock);
    int32_t v = inst->vel_counts_per_s;
    portEXIT_CRITICAL(&inst->lock);
    return v;
}

bool magnetic_encoder_inst_is_ok(magnetic_encoder_handle_t enc)
{
    magnetic_encoder_inst_t *inst = (magnetic_encoder_inst_t *)enc;
    portENTER_CRITICAL(&inst->lock);
    bool ok = inst->fail.ok;
    portEXIT_CRITICAL(&inst->lock);
    return ok;
}

bool magnetic_encoder_inst_get_sample(magnetic_encoder_handle_t enc,
                                      magnetic_encoder_sample_t *out)
{
    if (enc == NULL || out == NULL) {
        return false;
    }
    magnetic_encoder_inst_t *inst = (magnetic_encoder_inst_t *)enc;
    portENTER_CRITICAL(&inst->lock);
    /* 在快照锁内读时间，不能用获取锁之前的 now 判断更新后的样本。 */
    int64_t now_us = esp_timer_get_time();
    bool fresh = inst->has_sample && inst->sampled_at_us >= 0
        && now_us >= inst->sampled_at_us
        && now_us - inst->sampled_at_us <= MAGNETIC_ENCODER_MAX_CONTINUOUS_GAP_US;
    *out = (magnetic_encoder_sample_t){
        .raw_counts = inst->last_raw,
        .status = inst->status,
        .velocity_counts_per_s = inst->vel_counts_per_s,
        .velocity_span_us = inst->velocity_span_us,
        .velocity_valid = inst->velocity_valid && fresh && inst->last_attempt_ok,
        .position_counts = inst->pos_counts,
        .sampled_at_us = inst->sampled_at_us,
        .sample_seq = inst->sample_seq,
        .failure_seq = inst->failure_seq,
        .continuity_seq = inst->continuity_seq,
        .valid = inst->has_sample,
        .last_attempt_ok = inst->last_attempt_ok,
        .ok = inst->fail.ok,
    };
    portEXIT_CRITICAL(&inst->lock);
    return true;
}

/* ================================================================
 * 生命周期
 * ================================================================ */

esp_err_t magnetic_encoder_skeleton_start(magnetic_encoder_inst_t *inst,
                                          const magnetic_encoder_impl_t *impl,
                                          void *impl_ctx,
                                          const char *name)
{
    if (inst == NULL || impl == NULL || name == NULL
        || impl->read_frame == NULL || impl->counts_per_rev == NULL) {
        return ESP_ERR_INVALID_ARG;
    }

    /* 全量接管实例：清零 + 显式初始化器/初值 */
    memset(inst, 0, sizeof(*inst));
    inst->lock = (portMUX_TYPE)portMUX_INITIALIZER_UNLOCKED;
    inst->ops = (struct magnetic_encoder_s){
        .counts_per_rev        = magnetic_encoder_inst_counts_per_rev,
        .angle_counts          = magnetic_encoder_inst_angle_counts,
        .position_counts       = magnetic_encoder_inst_position_counts,
        .velocity_counts_per_s = magnetic_encoder_inst_velocity_counts_per_s,
        .is_ok                 = magnetic_encoder_inst_is_ok,
        .get_sample            = magnetic_encoder_inst_get_sample,
    };
    inst->impl     = impl;
    inst->impl_ctx = impl_ctx;
    inst->name     = name;

    magnetic_encoder_tracker_reset(&inst->tracker);
    magnetic_encoder_vel_win_reset(&inst->vel);
    magnetic_encoder_fail_reset(&inst->fail);      /* ok=true 起步 */

    /* 首读：种子多圈位置（pos=0）并验证链路可用 */
    uint32_t raw = 0;
    uint8_t status = 0;
    if (impl->read_frame(impl_ctx, &raw, &status)) {
        publish_sample(inst, raw, status);
        ESP_LOGI(name, "在线——首读 raw=%u（种子，pos=0）", raw);
    } else {
        /* 首读失败计入序列，但保持原 is_ok 初始为 true 的语义。 */
        inst->failure_seq++;
        inst->last_attempt_ok = false;
        char desc[96];
        fail_desc_of(inst, desc, sizeof(desc));
        ESP_LOGW(name, "首读失败（%s）——采样任务将继续重试", desc);
    }

    BaseType_t ok = xTaskCreatePinnedToCore(skeleton_task, name,
                                            ME_SKELETON_TASK_STACK, inst,
                                            ME_SKELETON_TASK_PRIO, NULL,
                                            ME_SKELETON_TASK_CORE);
    if (ok != pdPASS) {
        ESP_LOGE(name, "创建采样任务失败");
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(name, "采样任务已启动：1 kHz，优先级 %d，CPU%d，%d counts/rev",
             ME_SKELETON_TASK_PRIO, ME_SKELETON_TASK_CORE,
             (int)impl->counts_per_rev(impl_ctx));
    return ESP_OK;
}
