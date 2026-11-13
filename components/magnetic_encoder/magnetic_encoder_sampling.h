/* 采样实验时基与纯统计逻辑；不访问硬件或RTOS。 */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
#ifdef CONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ
#define ME_SAMPLE_PERIOD_US 500
#else
#define ME_SAMPLE_PERIOD_US 1000
#endif
#define ME_SAMPLE_RATE_HZ (1000000 / ME_SAMPLE_PERIOD_US)

typedef struct {
    uint64_t attempts, failures, skipped_cycles, discarded_notifications;
    uint64_t read_overruns, work_overruns;
    int64_t success_interval_min_us, success_interval_max_us;
    int64_t read_max_us, work_max_us, wake_max_us;
    int64_t last_success_us;
    int64_t first_attempt_us;
} magnetic_encoder_sampling_stats_t;

/* 从实际时间去重；第一次周期编号0合法。返回false时不修改last_cycle。 */
static inline bool magnetic_encoder_sampling_due(int64_t epoch_us, int64_t now_us,
                                                int64_t *last_cycle, uint64_t *skipped)
{
    if (now_us < epoch_us || !last_cycle || !skipped) return false;
    int64_t cycle = (now_us - epoch_us) / ME_SAMPLE_PERIOD_US;
    if (cycle <= *last_cycle) return false;
    if (*last_cycle >= 0) *skipped += (uint64_t)(cycle - *last_cycle - 1);
    *last_cycle = cycle;
    return true;
}

static inline void magnetic_encoder_sampling_record(
    magnetic_encoder_sampling_stats_t *s, int64_t begin, int64_t read_end,
    int64_t work_end, int64_t notified_at, bool ok)
{
    if (!s->attempts) s->first_attempt_us = begin;
    s->attempts++;
    if (!ok) s->failures++;
    int64_t read = read_end - begin, work = work_end - begin;
    if (read > s->read_max_us) s->read_max_us = read;
    if (work > s->work_max_us) s->work_max_us = work;
    if (read > ME_SAMPLE_PERIOD_US) s->read_overruns++;
    if (work > ME_SAMPLE_PERIOD_US) s->work_overruns++;
    if (notified_at >= 0 && begin >= notified_at && begin - notified_at > s->wake_max_us)
        s->wake_max_us = begin - notified_at;
    if (ok) {
        if (s->last_success_us > 0 && read_end > s->last_success_us) {
            int64_t dt = read_end - s->last_success_us;
            if (!s->success_interval_min_us || dt < s->success_interval_min_us)
                s->success_interval_min_us = dt;
            if (dt > s->success_interval_max_us) s->success_interval_max_us = dt;
        }
        s->last_success_us = read_end;
    }
}
