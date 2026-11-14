/* 真实采样时间速度窗：纯函数单元测试，不触碰设备。 */
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include "magnetic_encoder_core.h"

int main(void)
{
    magnetic_encoder_vel_win_t w;
    magnetic_encoder_vel_win_reset(&w);
    magnetic_encoder_velocity_t v;
    for (int i = 0; i < 17; ++i) {
        v = magnetic_encoder_vel_push_at(&w, i * 200, i * 2000, 20000);
        assert(v.valid == (i == 16));
    }
    assert(v.counts_per_s == 100000 && v.span_us == 32000);
    /* 超过总跨度1us即无效；不清位置历史，滑窗自然恢复。 */
    v = magnetic_encoder_vel_push_at(&w, 3400, 34001, 20000);
    assert(!v.valid && v.span_us == 32001);
    for (int i = 1; i <= 16; ++i)
        v = magnetic_encoder_vel_push_at(&w, 3400+i*100, 34001+i*1000, 20000);
    assert(v.valid && v.span_us == 16000 && v.counts_per_s == 100000);
    /* 非单调时钟重新播种，不将无效状态当作零速。 */
    v = magnetic_encoder_vel_push_at(&w, 3300, 32000, 20000);
    assert(!v.valid);
    for (int i = 1; i <= 16; ++i)
        v = magnetic_encoder_vel_push_at(&w, 3300-i*100, 32000+i*1000, 20000);
    assert(v.valid && v.counts_per_s == -100000);
    v = magnetic_encoder_vel_push_at(&w, 100, 68001, 20000);
    assert(!v.valid);
    magnetic_encoder_vel_win_reset(&w);
    for (int i = 0; i < 17; ++i) {
        int t = i*1000 + (i%2)*200;
        v = magnetic_encoder_vel_push_at(&w, t/10, t, 20000);
    }
    assert(v.valid && v.counts_per_s == 100000);
    /* 差值/结果溢出不产生伪低速。 */
    magnetic_encoder_vel_win_reset(&w);
    for (int i = 0; i < 17; ++i)
        v = magnetic_encoder_vel_push_at(&w, i == 0 ? INT64_MIN : INT64_MAX,
                                       i*1000, 20000);
    assert(!v.valid);
    magnetic_encoder_vel_win_reset(&w);
    for (int i = 0; i < 17; ++i)
        v = magnetic_encoder_vel_push_at(&w, (int64_t)i*INT32_MAX, i*1000, 20000);
    assert(!v.valid);
    /* 20 ms 等值允许，超过边界清窗；倒退时刻重新播种。 */
    magnetic_encoder_vel_win_reset(&w);
    for (int i = 0; i < 17; ++i)
        v = magnetic_encoder_vel_push_at(&w, i*20, i*20000, 20000);
    assert(!v.valid && v.span_us == 320000);
    assert(!magnetic_encoder_vel_push_at(&w, 341, 340001, 20000).valid);
    assert(!magnetic_encoder_vel_push_at(&w, 300, 300000, 20000).valid);
    for (int i = 1; i <= 16; ++i) {
        v = magnetic_encoder_vel_push_at(&w, 300+i, 300000+i*1000, 20000);
        assert(v.valid == (i == 16));
    }
    assert(v.counts_per_s == 1000 && v.span_us == 16000);
    /* 两实例独立；无效时间清空，负速度与静止均能明确有效。 */
    magnetic_encoder_vel_win_t other;
    magnetic_encoder_vel_win_reset(&w);
    magnetic_encoder_vel_win_reset(&other);
    for (int i = 0; i < 17; ++i) {
        v = magnetic_encoder_vel_push_at(&w, 100, i*1000, 20000);
        magnetic_encoder_velocity_t b = magnetic_encoder_vel_push_at(
            &other, -i*100, i*1000, 20000);
        if (i == 16) assert(b.valid && b.counts_per_s == -100000);
    }
    assert(v.valid && v.counts_per_s == 0);
    assert(!magnetic_encoder_vel_push_at(&w, 100, -1, 20000).valid);
    for (int i = 0; i < 17; ++i) {
        v = magnetic_encoder_vel_push_at(&w, 100, 20000+i*1000, 20000);
        assert(v.valid == (i == 16));
    }
    assert(v.counts_per_s == 0);
    assert(!magnetic_encoder_vel_push_at(&w, 100, 20000, 0).valid);
    assert(!magnetic_encoder_vel_push_at(NULL, 100, 20000, 20000).valid);
    /* 恒加速度：速度为两个采样时刻之间的平均值。 */
    magnetic_encoder_vel_win_reset(&w);
    for (int i = 0; i < 17; ++i)
        v = magnetic_encoder_vel_push_at(&w, i*i, i*1000, 20000);
    assert(v.valid && v.counts_per_s == 16000);
    puts("timed velocity checks passed");
}
