/*
 * magnetic_encoder_skeleton — 采样骨架（类别组件内部）
 *
 * 默认 1 kHz、可选 2 kHz 任务（CPU1、优先级3）调用单次采样服务。服务通过注入的读帧
 * 回调访问总线，并用单调时钟记录完成时间。失败计数、速度窗和快照
 * 均属于实例状态；公开快照读取与发布共用实例锁。
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

/* ---- 任务布局（契约不变量：CPU1、优先级 3） ---- */
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
    int64_t now_us = inst->now_us(inst->clock_ctx);
    portENTER_CRITICAL(&inst->lock);
    bool recovered = magnetic_encoder_fail_step(&inst->fail, true);

    /* 空窗不能通过最短角差猜测跨过了多少整圈。保留累计基准，但用
     * 当前 raw 重新播种；连续性序列通知位置解释层必须重新定位。 */
    bool broken = inst->has_sample && (now_us <= inst->sampled_at_us ||
        now_us - inst->sampled_at_us > inst->continuous_gap_us);
    int64_t pos;
    if (broken) {
        inst->continuity_seq++;
        int32_t cpr = inst->impl->counts_per_rev(inst->impl_ctx);
        inst->tracker.last_raw = raw % (uint32_t)(cpr > 0 ? cpr : 1);
        magnetic_encoder_vel_win_reset(&inst->vel);
        pos = inst->pos_counts;
    } else {
        pos = magnetic_encoder_tracker_update(
            &inst->tracker, raw, inst->impl->counts_per_rev(inst->impl_ctx));
    }
    inst->pos_counts = pos;
    inst->last_raw = raw;
    inst->status = status;
    magnetic_encoder_velocity_t velocity = magnetic_encoder_vel_push_at(
        &inst->vel, pos, now_us, inst->continuous_gap_us);
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

static bool sample_once_timed(magnetic_encoder_inst_t *inst, int64_t *read_end)
{
    uint32_t raw = 0;
    uint8_t status = 0;
    bool read_ok = inst->impl->read_frame(inst->impl_ctx, &raw, &status);
    if (read_end) *read_end = inst->now_us(inst->clock_ctx);
    if (read_ok) {
        if (publish_sample(inst, raw, status)) {
            ESP_LOGI(inst->name, "读取在连续 %d 次失败后恢复",
                     MAGNETIC_ENCODER_FAIL_LIMIT);
        }
        if (inst->impl->on_sample != NULL)
            inst->impl->on_sample(inst->impl_ctx, status);
        return true;
    }
    if (fail_step_locked(inst, false)) {
        char desc[96];
        fail_desc_of(inst, desc, sizeof(desc));
        ESP_LOGE(inst->name, "连续 %d 次读取失败——编码器标记 NOT OK（%s）",
                 MAGNETIC_ENCODER_FAIL_LIMIT, desc);
    }
    return false;
}

bool magnetic_encoder_sampler_sample_once(magnetic_encoder_inst_t *inst)
{
    return sample_once_timed(inst, NULL);
}

/* ================================================================
 * 采样任务（CPU1）
 * ================================================================ */

#ifdef CONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ
/* esp_timer 任务回调只通知，不执行SPI，也不在回调内补采。 */
static void sampling_tick(void *arg)
{
    magnetic_encoder_inst_t *inst = arg;
    portENTER_CRITICAL(&inst->lock);
    inst->notified_at_us = esp_timer_get_time();
    portEXIT_CRITICAL(&inst->lock);
    xTaskNotifyGive(inst->sample_task);
}
#endif

#ifdef CONFIG_MAGNETIC_ENCODER_SAMPLING_STATS
/* 采样任务只聚合RAM；日志格式化/写出不在采样路径执行。 */
static void sampling_stats_task(void *arg)
{
    magnetic_encoder_inst_t *inst = arg;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(5000));
        portENTER_CRITICAL(&inst->lock);
        magnetic_encoder_sampling_stats_t s = inst->sampling_stats;
        portEXIT_CRITICAL(&inst->lock);
        ESP_LOGI(inst->name,
            "采样统计 target=%dHz elapsed_us=%lld attempts=%llu fail=%llu skipped=%llu discarded=%llu "
            "success_dt_us=[%lld,%lld] read_max_us=%lld work_max_us=%lld "
            "latest_notify_to_start_max_us=%lld read_overrun=%llu work_overrun=%llu",
            ME_SAMPLE_RATE_HZ, (long long)(esp_timer_get_time() - s.first_attempt_us),
            (unsigned long long)s.attempts,
            (unsigned long long)s.failures, (unsigned long long)s.skipped_cycles,
            (unsigned long long)s.discarded_notifications,
            (long long)s.success_interval_min_us, (long long)s.success_interval_max_us,
            (long long)s.read_max_us, (long long)s.work_max_us, (long long)s.wake_max_us,
            (unsigned long long)s.read_overruns, (unsigned long long)s.work_overruns);
    }
}
#endif

static void skeleton_task(void *arg)
{
    magnetic_encoder_inst_t *inst = (magnetic_encoder_inst_t *)arg;

#ifdef CONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ
    int64_t last_cycle = -1;
#else
    TickType_t last_wake = xTaskGetTickCount();
#endif

    bool wdt_ok = false;
    bool wdt_attempted = false;

    while (1) {
        int64_t notified_at = -1;
#ifdef CONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ
        uint32_t notices = ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        portENTER_CRITICAL(&inst->lock);
        notified_at = inst->notified_at_us;
        if (notices > 1) inst->sampling_stats.discarded_notifications += notices - 1;
        uint64_t skipped = 0;
        bool due = magnetic_encoder_sampling_due(inst->timer_epoch_us,
            esp_timer_get_time(), &last_cycle, &skipped);
        inst->sampling_stats.skipped_cycles += skipped;
        if (!due) inst->sampling_stats.discarded_notifications++;
        portEXIT_CRITICAL(&inst->lock);
        if (!due) continue;
#endif
        /* 2 kHz定时器启动成功并通知后才订阅，启动失败清理等待任务时
         * 不遗留已删除任务的看门狗订阅。 */
        if (!wdt_attempted) {
            wdt_attempted = true;
            wdt_ok = (esp_task_wdt_add(NULL) == ESP_OK);
            if (!wdt_ok) ESP_LOGW(inst->name, "任务看门狗订阅失败——采样任务不受监控");
        }
        int64_t begin = esp_timer_get_time();
        int64_t read_end;
        bool read_ok = sample_once_timed(inst, &read_end);


        if (wdt_ok) {
            esp_task_wdt_reset();
        }

        int64_t work_end = esp_timer_get_time();
        portENTER_CRITICAL(&inst->lock);
        magnetic_encoder_sampling_record(&inst->sampling_stats, begin, read_end,
            work_end, notified_at, read_ok);
        portEXIT_CRITICAL(&inst->lock);
#ifdef CONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ
        /* 读取期间积压的通知不补采；下一轮只等待后续通知。实际周期编号
         * 再次去重，防止延迟回调在同一周期反复触发读取。 */
        uint32_t discarded = ulTaskNotifyTake(pdTRUE, 0);
        portENTER_CRITICAL(&inst->lock);
        inst->sampling_stats.discarded_notifications += discarded;
        portEXIT_CRITICAL(&inst->lock);
#else
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(ME_SKELETON_PERIOD_MS));
#endif
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

static bool set_continuous_gap_us(magnetic_encoder_handle_t enc, int64_t gap_us)
{
    if (!enc || gap_us <= 0 || gap_us > MAGNETIC_ENCODER_MAX_CONTINUOUS_GAP_US)
        return false;
    magnetic_encoder_inst_t *inst = (magnetic_encoder_inst_t *)enc;
    portENTER_CRITICAL(&inst->lock);
    if (gap_us != inst->continuous_gap_us) {
        inst->continuous_gap_us = gap_us;
        inst->continuity_seq++;
        magnetic_encoder_vel_win_reset(&inst->vel);
        inst->velocity_valid = false;
    }
    portEXIT_CRITICAL(&inst->lock);
    return true;
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
    int64_t now_us = inst->now_us(inst->clock_ctx);
    bool fresh = inst->has_sample && inst->sampled_at_us >= 0
        && now_us >= inst->sampled_at_us
        && now_us - inst->sampled_at_us <= inst->continuous_gap_us;
    *out = (magnetic_encoder_sample_t){
        .continuous_gap_us = inst->continuous_gap_us,
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

esp_err_t magnetic_encoder_sampler_init(magnetic_encoder_inst_t *inst,
    const magnetic_encoder_impl_t *impl, void *impl_ctx, const char *name,
    int64_t (*clock)(void *ctx), void *clock_ctx)
{
    if (inst == NULL || impl == NULL || name == NULL || clock == NULL
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
        .set_continuous_gap_us = set_continuous_gap_us,
    };
    inst->continuous_gap_us = MAGNETIC_ENCODER_MAX_CONTINUOUS_GAP_US;
    inst->impl     = impl;
    inst->impl_ctx = impl_ctx;
    inst->name     = name;
    inst->now_us = clock;
    inst->clock_ctx = clock_ctx;

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

    return ESP_OK;
}

static int64_t monotonic_clock(void *ctx)
{
    (void)ctx;
    return esp_timer_get_time();
}

esp_err_t magnetic_encoder_skeleton_start(magnetic_encoder_inst_t *inst,
    const magnetic_encoder_impl_t *impl, void *impl_ctx, const char *name)
{
    esp_err_t result = magnetic_encoder_sampler_init(inst, impl, impl_ctx, name,
                                                    monotonic_clock, NULL);
    if (result != ESP_OK) return result;

#ifdef CONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ
    esp_timer_create_args_t timer_args = {
        .callback = sampling_tick, .arg = inst, .dispatch_method = ESP_TIMER_TASK,
        .name = name, .skip_unhandled_events = true,
    };
    esp_err_t err = esp_timer_create(&timer_args, &inst->sample_timer);
    if (err != ESP_OK) return err;
    TaskHandle_t *task_out = &inst->sample_task;
#else
    void *task_out = NULL;
#endif

    BaseType_t ok = xTaskCreatePinnedToCore(skeleton_task, name,
                                            ME_SKELETON_TASK_STACK, inst,
                                            ME_SKELETON_TASK_PRIO, task_out,
                                            ME_SKELETON_TASK_CORE);
    if (ok != pdPASS) {
#ifdef CONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ
        esp_timer_delete(inst->sample_timer);
#endif
        ESP_LOGE(name, "创建采样任务失败");
        return ESP_ERR_NO_MEM;
    }
#ifdef CONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ
    inst->timer_epoch_us = esp_timer_get_time();
    err = esp_timer_start_periodic(inst->sample_timer, ME_SAMPLE_PERIOD_US);
    if (err != ESP_OK) {
        vTaskDelete(inst->sample_task);
        esp_timer_delete(inst->sample_timer);
        return err;
    }
#endif
#ifdef CONFIG_MAGNETIC_ENCODER_SAMPLING_STATS
    if (xTaskCreatePinnedToCore(sampling_stats_task, "encoder_stats", 3072, inst,
                               1, NULL, ME_SKELETON_TASK_CORE) != pdPASS) {
        ESP_LOGW(name, "统计导出任务创建失败；采样继续但无周期统计日志");
    }
#endif

    ESP_LOGI(name, "采样任务已启动：目标 %d Hz，优先级 %d，CPU%d，%d counts/rev",
             ME_SAMPLE_RATE_HZ, ME_SKELETON_TASK_PRIO, ME_SKELETON_TASK_CORE,
             (int)impl->counts_per_rev(impl_ctx));
    return ESP_OK;
}
