/* 跟随误差窗口判定；只保存观察历史，不改变编码器或STEP位置。 */
#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    bool initialized;
    uint32_t run;
    int64_t window_start_us, start_abs_um, growth_um, window_elapsed_us;
    unsigned growing_windows;
} cartfsm_following_error_t;

/* 返回0=继续，1=累计硬限，2=连续窗口增长。参数由Kconfig约束。 */
static inline int cartfsm_following_error_update(cartfsm_following_error_t *s,
    uint32_t run, int64_t now_us, int64_t error_um, int64_t soft_um,
    int64_t hard_um, int64_t window_us, int64_t growth_um, unsigned windows)
{
    int64_t magnitude = error_um < 0 ? -error_um : error_um;
    if (!s->initialized || s->run != run || now_us < s->window_start_us) {
        *s = (cartfsm_following_error_t){.initialized=true, .run=run,
            .window_start_us=now_us, .start_abs_um=magnitude};
    }
    if (magnitude >= hard_um) return 1;
    int64_t elapsed = now_us - s->window_start_us;
    if (elapsed < window_us) return 0;
    s->growth_um = magnitude - s->start_abs_um;
    s->window_elapsed_us = elapsed;
    /* 延迟的监督拍按真实窗长提高增长门限，不把较长积累当高增长率。 */
    bool growing = s->growth_um > 0 &&
        s->growth_um * window_us >= growth_um * elapsed;
    s->growing_windows = growing ? s->growing_windows + 1 : 0;
    if (s->growing_windows > windows) s->growing_windows = windows;
    s->window_start_us = now_us;
    s->start_abs_um = magnitude;
    return magnitude > soft_um && s->growing_windows >= windows ? 2 : 0;
}
