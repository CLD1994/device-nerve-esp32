/* 编码器快照单元测试：推进骨架发布边界，硬件任务由替身隔离。 */
#include <assert.h>
#include <stdio.h>
#include "magnetic_encoder_skeleton.c"

static int64_t now;
int64_t esp_timer_get_time(void) { return now; }
void vTaskDelay(TickType_t ticks) { now += ticks * 1000; }
static int32_t cpr(void *ctx) { (void)ctx; return 4096; }
static bool read_fail(void *ctx, uint32_t *raw, uint8_t *status)
{
    (void)ctx;
    (void)raw;
    (void)status;
    return false;
}

int main(void)
{
    magnetic_encoder_inst_t inst;
    magnetic_encoder_impl_t impl = {
        .counts_per_rev = cpr, .read_frame = read_fail,
    };
    assert(magnetic_encoder_skeleton_start(&inst, &impl, NULL, "sample") == ESP_OK);
    magnetic_encoder_handle_t enc = (magnetic_encoder_handle_t)&inst;
    magnetic_encoder_sample_t s;

    /* 原 is_ok 初始为 true，但没有样本时不能用作标定。 */
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(!s.valid && s.ok && !s.last_attempt_ok);
    assert(s.failure_seq == 1 && s.sample_seq == 0);

    now = 1000;
    publish_sample(&inst, 10, 0);
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(s.valid && s.ok && s.last_attempt_ok);
    assert(s.sample_seq == 1 && s.failure_seq == 1);
    assert(s.sampled_at_us == 1000 && s.position_counts == 0);

    now = 2000;
    publish_sample(&inst, 12, 0);
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(s.sampled_at_us == 2000 && s.position_counts == 2);

    for (int i = 0; i < 10; i++) {
        fail_step_locked(&inst, false);
    }
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(s.valid && !s.ok && !s.last_attempt_ok);
    assert(s.failure_seq == 11);
    assert(s.sampled_at_us == 2000 && s.position_counts == 2);

    /* 恢复不能抹去失败历史或过长的采样空窗。 */
    now = 30000;
    publish_sample(&inst, 14, 0);
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(s.ok && s.last_attempt_ok && s.failure_seq == 11);
    assert(s.continuity_seq == 1);
    assert(s.sampled_at_us == 30000 && s.position_counts == 2);

    assert(!magnetic_encoder_get_sample(NULL, &s));
    assert(!magnetic_encoder_get_sample(enc, NULL));
    struct magnetic_encoder_s unsupported = { 0 };
    s.sample_seq = 999;
    assert(!magnetic_encoder_get_sample(&unsupported, &s));
    assert(s.sample_seq == 999);

    now = 50000;
    publish_sample(&inst, 16, 0);
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(s.continuity_seq == 1); /* 正好 20 ms 允许 */
    now = 70001;
    publish_sample(&inst, 18, 0);
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(s.continuity_seq == 2);
    /* 满窗速度与位置/原始角/状态来自同一发布；随后失效不伪造零速。 */
    for (int i = 1; i <= 16; ++i) {
        now += 1000;
        publish_sample(&inst, 18 + i*2, 3);
    }
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(s.velocity_valid && s.velocity_counts_per_s == 2000);
    assert(s.velocity_span_us == 16000 && s.raw_counts == 50 && s.status == 3);
    now += 20001;
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(!s.velocity_valid && s.velocity_counts_per_s == 2000);
    publish_sample(&inst, 52, 0);
    assert(magnetic_encoder_get_sample(enc, &s) && !s.velocity_valid);
    for (int i = 1; i <= 16; ++i) {
        now += 1000;
        publish_sample(&inst, 52 + i*2, 0);
    }
    assert(magnetic_encoder_get_sample(enc, &s) && s.velocity_valid);
    fail_step_locked(&inst, false);
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(!s.velocity_valid && s.ok && s.velocity_counts_per_s == 2000);
    for (int i = 1; i <= 16; ++i) {
        now += 1000;
        publish_sample(&inst, 84 + i*2, 0);
        assert(magnetic_encoder_get_sample(enc, &s) && !s.velocity_valid);
    }
    now += 1000;
    publish_sample(&inst, 118, 0);
    assert(magnetic_encoder_get_sample(enc, &s) && s.velocity_valid);
    uint64_t continuity = s.continuity_seq;
    publish_sample(&inst, 120, 0); /* 同一个时间戳不能构成有效速度。 */
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(!s.velocity_valid && s.continuity_seq == continuity + 1);
    /* 每点及时但整个窗口过长：位置连续性保留，速度明确无效。 */
    continuity = s.continuity_seq;
    int64_t before_window = s.position_counts;
    for (int i = 1; i <= 16; ++i) {
        now += 20000;
        publish_sample(&inst, 120 + i*2, 0);
    }
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(!s.velocity_valid && s.velocity_span_us == 320000);
    assert(s.continuity_seq == continuity && s.position_counts == before_window + 32);
    for (int i = 1; i <= 16; ++i) {
        now += 1000;
        publish_sample(&inst, 152 + i*2, 0);
    }
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(s.velocity_valid && s.velocity_span_us == 16000 && s.velocity_counts_per_s == 2000);
    /* 40 mm/rev、1250 mm/s 下 17 ms 位移 21.25 mm，已超过半圈。
     * 5 ms 工程预算必须在 unwrap 之前拒绝跨空窗位移。 */
    assert(magnetic_encoder_set_continuous_gap_us(enc, 5000));
    int64_t previous = inst.pos_counts;
    uint64_t old_seq = inst.continuity_seq;
    uint32_t start_raw = inst.last_raw;
    now += 17000;
    publish_sample(&inst, (start_raw + 2176) % 4096, 0);
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(s.position_counts == previous && s.continuity_seq == old_seq+1);
    assert(!s.velocity_valid && s.continuous_gap_us == 5000);
    for (int i = 1; i <= 16; i++) {
        now += 1000;
        publish_sample(&inst, (start_raw+2176+i*128)%4096, 0);
    }
    assert(magnetic_encoder_get_sample(enc, &s));
    assert(s.velocity_valid && s.velocity_counts_per_s == 128000);
    assert(s.continuity_seq == old_seq+1); /* 恢复不能抹去丢圈历史。 */
    now += 5001;
    assert(magnetic_encoder_get_sample(enc, &s) && !s.velocity_valid);
    puts("sample snapshot checks passed");
    return 0;
}
