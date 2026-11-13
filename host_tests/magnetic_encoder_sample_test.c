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
    assert(s.sampled_at_us == 30000 && s.position_counts == 4);

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
    puts("sample snapshot checks passed");
    return 0;
}
