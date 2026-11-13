/* 参考点单元测试：可控时钟和编码器快照替身，无硬件或真实任务。 */
#include <assert.h>
#include <stdio.h>
#include <limits.h>
#include "cartpos.h"
#include "settings.h"
#include "freertos/task.h"

typedef enum {
    GOOD, NO_SAMPLE, STALE, MOVING, READ_FAILURE, GAP, FROZEN,
    LAST_READ_FAILED, SCALE_CHANGE, RANGE_BOUNDARY, AGE_BOUNDARY,
    FUTURE_SAMPLE, UNHEALTHY, OBSERVER_GAP,
} scenario_t;
static int64_t now = 1000000;
static uint64_t seq, failure_count, gap_count;
static scenario_t scenario;
static int calls;
static bool rebase_during_sample;
static int64_t current_position = 5000;
static float upr = 40;
static settings_change_cb_t callback;

float settings_units_per_rev(void) { return upr; }
bool settings_subscribe(settings_change_cb_t cb) { callback = cb; return true; }
int64_t esp_timer_get_time(void) { return now; }
void vTaskDelay(TickType_t ticks)
{
    now += scenario == OBSERVER_GAP ? 21000 : 1000 * ticks;
}
static bool configure_gap(magnetic_encoder_handle_t h, int64_t gap)
{ (void)h; assert(gap == 5000 || gap == 5125); return true; }
static int32_t cpr(magnetic_encoder_handle_t h) { (void)h; return 40000; }
static int64_t pos(magnetic_encoder_handle_t h) { (void)h; return current_position; }
static int32_t vel(magnetic_encoder_handle_t h) { (void)h; return 0; }
static bool ok(magnetic_encoder_handle_t h) { (void)h; return true; }
static bool sample(magnetic_encoder_handle_t h, magnetic_encoder_sample_t *s)
{
    (void)h;
    ++calls;
    *s = (magnetic_encoder_sample_t){
        .continuous_gap_us = 5000, .valid = true, .velocity_valid=true, .ok = true, .last_attempt_ok = true,
        .sample_seq = ++seq, .sampled_at_us = now,
        .failure_seq = failure_count, .continuity_seq = gap_count,
        .position_counts = current_position,
    };
    switch (scenario) {
    case NO_SAMPLE: s->valid = false; break;
    case STALE: s->sampled_at_us = now - 20001; break;
    case MOVING: if (calls > 2) s->position_counts += 101; break;
    case READ_FAILURE:
        if (calls > 2) s->failure_seq = ++failure_count;
        break;
    case GAP:
        if (calls > 2) s->continuity_seq = ++gap_count;
        break;
    case FROZEN: s->sample_seq = 1; break;
    case LAST_READ_FAILED: s->last_attempt_ok = false; break;
    case SCALE_CHANGE:
        if (calls > 2) {
            upr = 41;
            callback(SET_MM_PER_REV, upr);
        }
        break;
    case RANGE_BOUNDARY: if (calls > 2) s->position_counts += 100; break;
    case AGE_BOUNDARY: s->sampled_at_us = now - 5000; break;
    case FUTURE_SAMPLE: s->sampled_at_us = now + 1; break;
    case UNHEALTHY: s->ok = false; break;
    default: break;
    }
    if (rebase_during_sample) {
        rebase_during_sample = false;
        gap_count++;
        cartpos_reference_t newer;
        assert(cartpos_capture_reference(&newer));
        assert(cartpos_apply_reference(&newer, 0));
    }
    return true;
}
static struct magnetic_encoder_s encoder = {
    .set_continuous_gap_us = configure_gap, .counts_per_rev = cpr, .position_counts = pos,
    .velocity_counts_per_s = vel, .is_ok = ok, .get_sample = sample,
};
static void set_scale(float value)
{
    upr = value;
    callback(SET_MM_PER_REV, value);
}
static void select_scenario(scenario_t value)
{
    scenario = value;
    calls = 0;
}

int main(void)
{
    cartpos_init(&encoder, 2000);
    cartpos_reference_t ref = { .raw_um = 123 };
    assert(!cartpos_reference_is_valid());

    /* 每一种拒绝分支都不修改捕获输出，也不定基。 */
    const scenario_t rejected[] = {
        NO_SAMPLE, STALE, MOVING, READ_FAILURE, GAP, FROZEN,
        LAST_READ_FAILED, SCALE_CHANGE, FUTURE_SAMPLE, UNHEALTHY, OBSERVER_GAP,
    };
    for (unsigned i = 0; i < sizeof(rejected) / sizeof(rejected[0]); i++) {
        select_scenario(rejected[i]);
        set_scale(40);
        ref.raw_um = 123;
        assert(!cartpos_capture_reference(&ref));
        assert(ref.raw_um == 123);
        assert(cartpos_position_um() == 5000 || scenario == SCALE_CHANGE);
    }

    select_scenario(GOOD);
    set_scale(40);
    assert(cartpos_capture_reference(&ref));
    assert(ref.raw_um == 5000);
    assert(cartpos_apply_reference(&ref, 1000));
    assert(cartpos_position_um() == 1000);
    assert(cartpos_reference_is_valid());

    select_scenario(READ_FAILURE);
    calls = 3;
    assert(!cartpos_reference_is_valid());
    select_scenario(GOOD);
    assert(!cartpos_reference_is_valid()); /* 健康恢复不会解除失效锁存 */
    assert(!cartpos_apply_reference(&ref, -1000));
    assert(cartpos_capture_reference(&ref));
    assert(cartpos_apply_reference(&ref, -1000));
    assert(cartpos_position_um() == -1000);
    assert(cartpos_reference_is_valid());

    set_scale(41);
    assert(!cartpos_reference_is_valid());
    assert(!cartpos_apply_reference(&ref, 0));
    set_scale(40);
    assert(cartpos_capture_reference(&ref));
    assert(!cartpos_apply_reference(&ref, INT64_MIN));

    select_scenario(RANGE_BOUNDARY);
    assert(cartpos_capture_reference(&ref));
    assert(ref.raw_um == 5100);
    select_scenario(AGE_BOUNDARY);
    assert(cartpos_capture_reference(&ref));

    /* 提交过程中又移动了 1000 µm；apply 仍以捕获点定义零位。 */
    select_scenario(GOOD);
    assert(cartpos_capture_reference(&ref));
    current_position = 6000;
    assert(cartpos_apply_reference(&ref, 0));
    assert(cartpos_position_um() == 1000);
    assert(cartpos_reference_is_valid());
    select_scenario(STALE);
    assert(!cartpos_reference_is_valid());
    select_scenario(GOOD);
    assert(!cartpos_reference_is_valid());

    assert(cartpos_capture_reference(&ref));
    assert(cartpos_apply_reference(&ref, INT64_C(3000000000)));
    assert(cartpos_position_um() == INT64_C(3000000000));
    select_scenario(GAP);
    calls = 3;
    assert(!cartpos_reference_is_valid());
    select_scenario(GOOD);
    assert(!cartpos_reference_is_valid());

    assert(cartpos_capture_reference(&ref));
    set_scale(41);
    set_scale(40); /* 改回相同比例也不能复用旧版本捕获。 */
    assert(!cartpos_apply_reference(&ref, 0));
    assert(!cartpos_capture_reference(NULL));
    assert(!cartpos_apply_reference(NULL, 0));
    /* 稳定的新速度不能自动修复跨空窗后的绝对位置；必须重新定位。 */
    select_scenario(GOOD); set_scale(40);
    assert(cartpos_capture_reference(&ref));
    assert(cartpos_apply_reference(&ref, 0));
    cartpos_measurement_t m;
    assert(cartpos_get_measurement(&m));
    gap_count++;
    assert(!cartpos_get_measurement(&m));
    assert(!cartpos_reference_is_valid());
    assert(!cartpos_get_measurement(&m));
    assert(cartpos_capture_reference(&ref));
    assert(cartpos_apply_reference(&ref, -426662));
    assert(cartpos_get_measurement(&m) && m.x_um == -426662);
    assert(cartpos_reference_is_valid());
    /* 旧测量快照不能撤销刚刚成功提交的新参考。 */
    rebase_during_sample = true;
    assert(!cartpos_get_measurement(&m));
    assert(cartpos_get_measurement(&m));
    assert(cartpos_reference_is_valid());
    puts("reference checks passed");
    return 0;
}
