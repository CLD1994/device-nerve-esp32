/* 生产引擎独立编译；通过 GPTimer/GPIO 边界驱动并观察公开契约。 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "step_engine.h"
#include "driver/gptimer.h"
#include "driver/gpio.h"

int step_test_lock_depth;
static struct {
    uint64_t now, alarm;
    bool running;
    unsigned pulses, direction;
    gptimer_event_callbacks_t callbacks;
    void *context;
} timer;
static bool kick_during_pulse;
enum { STEP_PIN = 1, DIR_PIN = 2 };
esp_err_t gptimer_new_timer(const gptimer_config_t *c, gptimer_handle_t *t)
{ assert(c->resolution_hz == 1000000); *t = &timer; return ESP_OK; }
esp_err_t gptimer_register_event_callbacks(gptimer_handle_t t, const gptimer_event_callbacks_t *c, void *a)
{ assert(t == &timer); timer.callbacks = *c; timer.context = a; return ESP_OK; }
esp_err_t gptimer_enable(gptimer_handle_t t) { assert(t == &timer); return ESP_OK; }
esp_err_t gptimer_get_raw_count(gptimer_handle_t t, uint64_t *v)
{ assert(t == &timer); *v = timer.now; return ESP_OK; }
esp_err_t gptimer_stop(gptimer_handle_t t)
{ assert(t == &timer); timer.running = false; return ESP_OK; }
esp_err_t gptimer_start(gptimer_handle_t t)
{ assert(t == &timer); timer.running = true; return ESP_OK; }
esp_err_t gptimer_set_alarm_action(gptimer_handle_t t, const gptimer_alarm_config_t *a)
{ assert(t == &timer); timer.alarm = a->alarm_count; return ESP_OK; }
esp_err_t gpio_set_level(gpio_num_t pin, unsigned level)
{
    if (pin == STEP_PIN && level) {
        timer.pulses++;
        if (kick_during_pulse) {
            kick_during_pulse = false;
            timer.now++; /* 模拟另一核在 alarm 快照之后接收新目标。 */
            step_engine_vel_target(1000LL * 65536);
        }
    }
    if (pin == DIR_PIN) timer.direction = level;
    return ESP_OK;
}
static void deliver_alarm(void)
{
    timer.now = timer.alarm;
    gptimer_alarm_event_data_t event = { .alarm_value = timer.now, .count_value = timer.now };
    timer.callbacks.on_alarm(&timer, &event, timer.context);
    assert(step_test_lock_depth == 0);
}
static void reach_velocity(int64_t velocity)
{
    for (unsigned i = 0; i < 20000 && step_engine_vel_now_q16() != velocity; i++) {
        assert(timer.running);
        deliver_alarm();
    }
    assert(step_engine_vel_now_q16() == velocity);
}
static void check_target(int64_t request, int64_t expected)
{
    step_engine_vel_target(request);
    reach_velocity(expected);
    int32_t position = step_engine_position_steps();
    unsigned pulses = timer.pulses;
    deliver_alarm();
    assert(timer.pulses == pulses + 1);
    assert(step_engine_position_steps() == position + (expected > 0 ? 1 : -1));
    assert(step_engine_vel_now_q16() == expected);
}
int main(void)
{
    assert(step_engine_init(STEP_PIN, DIR_PIN) == ESP_OK);
    step_engine_vel_set_wdt_us(0);
    step_engine_vel_set_accel(4000);
    assert(step_engine_try_stop_at_rest());

    /* 小于一个整步/秒的残速也必须拒绝停机，不得把取整零当停稳。 */
    step_engine_vel_target(32768);
    reach_velocity(32768);
    int32_t position = step_engine_position_steps();
    uint64_t alarm = timer.alarm;
    assert(!step_engine_try_stop_at_rest());
    assert(timer.running && timer.alarm == alarm);
    assert(step_engine_vel_now_q16() == 32768);
    assert(step_engine_position_steps() == position);

    step_engine_vel_target(0);
    reach_velocity(0);
    assert(!timer.running && step_engine_try_stop_at_rest());
    unsigned pulses = timer.pulses;
    deliver_alarm(); /* 已挂起的回调不能在停稳后继续发步。 */
    assert(timer.pulses == pulses && !timer.running);
    assert(step_engine_position_steps() == position + 1);
    assert(step_engine_try_stop_at_rest());

    /* 停稳操作不是永久门禁，新的显式目标仍可启动。 */
    step_engine_vel_target(65536);
    assert(timer.running && !step_engine_try_stop_at_rest());
    step_engine_stop();
    position = step_engine_position_steps();
    pulses = timer.pulses;
    deliver_alarm();
    assert(!timer.running && timer.pulses == pulses);
    assert(step_engine_position_steps() == position && step_engine_vel_now_q16() == 0);

    step_engine_vel_set_accel(1000000);
    /* 数值来自对外约定，不能随生产常量一起漂移。 */
    const int64_t limit = 50000LL * 65536;
    assert(STEP_ENGINE_MAX_TARGET_HZ == 50000u);
    check_target(INT64_MAX, limit);             /* 静止启动 */
    check_target(INT64_MIN, -limit);            /* 运行中换向 */
    check_target(limit, limit);
    check_target(limit + 1, limit);
    assert(timer.alarm - timer.now == 20); /* 理想替身下 50 kHz 周期 */
    check_target(-limit, -limit);
    check_target(-limit - 1, -limit);
    assert(timer.alarm - timer.now == 20);
    check_target(-49999LL * 65536, -49999LL * 65536);
    step_engine_vel_target(0);
    reach_velocity(0);
    assert(step_engine_try_stop_at_rest());
    /* WDT 使用 alarm 时间快照；较新的喂狗不得被无符号减法当超时。 */
    const int64_t cruise = 1000LL * 65536;
    step_engine_vel_set_accel(1000000);

    step_engine_vel_set_wdt_us(0);
    step_engine_vel_target(cruise);
    reach_velocity(cruise);
    step_engine_vel_set_wdt_us(1000);
    kick_during_pulse = true;
    deliver_alarm();
    assert(step_engine_vel_now_q16() == cruise);
    assert(timer.running);

    /* 恰好到期不触发；超过一微秒后仍按原语义减速。 */
    uint64_t kick = timer.now;
    gptimer_alarm_event_data_t event = { .alarm_value = kick + 1000,
                                       .count_value = kick + 1000 };
    timer.now = event.count_value;
    timer.callbacks.on_alarm(&timer, &event, timer.context);
    assert(step_engine_vel_now_q16() == cruise);
    event.alarm_value = event.count_value = kick + 1001;
    timer.now = event.count_value;
    timer.callbacks.on_alarm(&timer, &event, timer.context);
    assert(step_engine_vel_now_q16() < cruise);
    step_engine_stop();
    /* 正、反向 WDT 都使用当前加速度；改加速度不喂狗、不换向、不复活目标。 */
    for (int sign = -1; sign <= 1; sign += 2) {
        step_engine_vel_set_wdt_us(0);
        step_engine_vel_set_accel(1000000);
        step_engine_vel_target(sign * cruise);
        reach_velocity(sign * cruise);
        step_engine_vel_set_accel(1000);
        step_engine_vel_set_wdt_us(10000);
        unsigned direction = timer.direction;
        timer.now += 10001;
        gptimer_alarm_event_data_t expired = { .alarm_value = timer.now,
                                               .count_value = timer.now };
        timer.callbacks.on_alarm(&timer, &expired, timer.context);
        assert(step_engine_vel_now_q16() == sign * 999LL * 65536);
        assert(timer.direction == direction);
        step_engine_vel_set_accel(999000);
        deliver_alarm(); /* 距改加速度仅约1ms，若错误喂狗将重新追踪非零目标。 */
        assert(step_engine_vel_now_q16() == 0 && !timer.running);
        assert(timer.direction == direction);
        unsigned stopped_pulses = timer.pulses;
        step_engine_vel_set_accel(2000);
        deliver_alarm(); /* 零速时改档不能启动或换向。 */
        assert(step_engine_vel_now_q16() == 0 && !timer.running);
        assert(timer.pulses == stopped_pulses && timer.direction == direction);
    }
    /* 普通目标0与HALT同用当前档，不改变WDT设置也不换向。 */
    for (int halt = 0; halt <= 1; ++halt) {
        step_engine_vel_set_wdt_us(0);
        step_engine_vel_set_accel(1000000);
        step_engine_vel_target(cruise);
        reach_velocity(cruise);
        step_engine_vel_set_accel(1000);
        if (halt) step_engine_vel_halt(); else step_engine_vel_target(0);
        unsigned direction = timer.direction;
        deliver_alarm();
        assert(step_engine_vel_now_q16() == 999LL * 65536);
        step_engine_vel_set_accel(999000);
        deliver_alarm();
        assert(step_engine_vel_now_q16() == 0 && !timer.running);
        assert(timer.direction == direction);
    }
    puts("step_engine_stop: public-contract assertions passed");
}

