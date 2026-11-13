/* 原子零速停机单元测试：生产引擎编入同一翻译单元，定时器/GPIO替身，不运行硬件。 */
#include <assert.h>
#include <stdio.h>
#include "../components/step_engine/step_engine.c"
int step_test_lock_depth;
static int stops,starts,pulses;
esp_err_t gptimer_stop(gptimer_handle_t t) {(void)t;stops++;return ESP_OK;}
esp_err_t gptimer_start(gptimer_handle_t t) {(void)t;starts++;return ESP_OK;}
esp_err_t gptimer_set_alarm_action(gptimer_handle_t t,const gptimer_alarm_config_t*a) {(void)t;(void)a;return ESP_OK;}
esp_err_t gpio_set_level(gpio_num_t p,unsigned l) {if(p==s_step_gpio && l)pulses++;return ESP_OK;}
int main(void) {
    assert(step_engine_init(1,2)==ESP_OK);
    s_stopped=false;s_timer_running=true;s_v_q16=1;s_target_q16=65536;s_chain_remaining_us=13;
    assert(!step_engine_try_stop_at_rest());
    assert(s_v_q16==1 && s_target_q16==65536 && !s_stopped && s_timer_running && s_chain_remaining_us==13 && stops==0);
    s_v_q16=65536;assert(!step_engine_try_stop_at_rest());assert(stops==0);
    s_v_q16=0;s_stopped=true;assert(step_engine_try_stop_at_rest());
    assert(s_stopped && !s_timer_running && s_target_q16==0 && s_chain_remaining_us==0 && stops==1);
    gptimer_alarm_event_data_t ev={.alarm_value=1000,.count_value=1000};
    int p=pulses,start=starts;gptimer_alarm_cb(s_timer,&ev,NULL);
    assert(pulses==p && starts==start && step_test_lock_depth==0);
    assert(step_engine_try_stop_at_rest());assert(s_v_q16==0 && s_target_q16==0);
    /* 实际递推自然停稳：本拍脉冲在零速发布之前，随后回调不得再发步。 */
    s_stopped=false;s_timer_running=true;s_v_q16=65536;s_target_q16=0;
    s_chain_remaining_us=0;s_accel=4000;s_wdt_us=0;
    p=pulses;gptimer_alarm_cb(s_timer,&ev,NULL);
    assert(pulses==p+1 && s_stopped && s_v_q16==0);
    assert(step_engine_try_stop_at_rest());
    p=pulses;start=starts;gptimer_alarm_cb(s_timer,&ev,NULL);
    assert(pulses==p && starts==start);
    /* 原子操作不是永久门禁：显式新目标仍可启动，阻止它由FSM负责。 */
    step_engine_vel_target(65536);
    assert(!s_stopped && s_v_q16>0 && starts>start);
    assert(!step_engine_try_stop_at_rest());
    puts("step_engine_stop: all assertions passed");
}
