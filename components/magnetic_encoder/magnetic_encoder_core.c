/*
 * magnetic_encoder_core — 骨架纯函数实现（契约见同名头）
 */

#include "magnetic_encoder_core.h"

#include <math.h>
#include <limits.h>
#include <string.h>

/* ---- 失败计数状态机 ---- */

void magnetic_encoder_fail_reset(magnetic_encoder_fail_t *f)
{
    if (f == NULL) {
        return;
    }
    f->streak = 0;
    f->ok     = true;
}

bool magnetic_encoder_fail_step(magnetic_encoder_fail_t *f, bool read_ok)
{
    if (f == NULL) {
        return false;
    }

    if (read_ok) {
        f->streak = 0;
        if (!f->ok) {
            f->ok = true;
            return true;        /* NOT OK 期间恢复——事件 */
        }
        return false;
    }

    f->streak++;
    if (f->streak == MAGNETIC_ENCODER_FAIL_LIMIT && f->ok) {
        f->ok = false;
        return true;           /* 首达 LIMIT 进入 NOT OK——事件 */
    }
    return false;
}

/* ---- 16 ms 速度窗 ---- */

void magnetic_encoder_vel_win_reset(magnetic_encoder_vel_win_t *w)
{
    if (w == NULL) {
        return;
    }
    memset(w, 0, sizeof(*w));
    w->head = -1;
}

magnetic_encoder_velocity_t magnetic_encoder_vel_push_at(
    magnetic_encoder_vel_win_t *w, int64_t pos, int64_t time_us,
    int64_t max_gap_us)
{
    magnetic_encoder_velocity_t result = {0};
    if (w == NULL) return result;
    if (time_us < 0 || max_gap_us <= 0) {
        magnetic_encoder_vel_win_reset(w);
        return result;
    }
    if (w->fill && (time_us <= w->time_us[w->head]
            || time_us - w->time_us[w->head] > max_gap_us)) {
        magnetic_encoder_vel_win_reset(w);
    }
    w->head = (w->head + 1) % MAGNETIC_ENCODER_HIST_LEN;
    w->hist[w->head] = pos;
    w->time_us[w->head] = time_us;
    if (w->fill < MAGNETIC_ENCODER_HIST_LEN) w->fill++;
    if (w->fill < MAGNETIC_ENCODER_HIST_LEN) return result;

    int oldest = (w->head + 1) % MAGNETIC_ENCODER_HIST_LEN;
    int64_t old = w->hist[oldest];
    result.span_us = time_us - w->time_us[oldest];
    if (result.span_us > MAGNETIC_ENCODER_MAX_VELOCITY_SPAN_US) return result;
    if ((old < 0 && pos > INT64_MAX + old)
            || (old > 0 && pos < INT64_MIN + old)) return result;
    double rate = (double)(pos - old) * 1000000.0 / (double)result.span_us;
    if (!isfinite(rate) || rate > INT32_MAX || rate < INT32_MIN) return result;
    result.counts_per_s = (int32_t)llround(rate);
    result.valid = true;
    return result;
}
