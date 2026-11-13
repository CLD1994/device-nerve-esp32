/* FSM电源门单元测试：真实命令路径，硬件和任务为替身。 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "cartpos.h"
#include "cartcal.h"
#include "cartaxis.h"
#include "cartproto.h"
#include "poleang.h"
#include "freertos/task.h"
int power_test_lock_depth;
static unsigned tmc_reads;
static bool tmc_read_ok=true;
bool tmc2209_read_reg(uint8_t reg,uint32_t *out) { assert(power_test_lock_depth==1);tmc_reads++;*out=reg;return tmc_read_ok; }
static bool require_lock;
static bool power, enabled, fail_at_enable;
static int stops, velocity;
static long position;
static char reply[40];
static bool referenced=true;
esp_err_t cartcal_load(cartcal_record_t *out) { *out=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};return ESP_OK; }
esp_err_t cartcal_save(const cartcal_record_t *r) { (void)r;return ESP_OK; }
float settings_units_per_rev(void) { return 40; }
bool cartpos_capture_reference(cartpos_reference_t *out) { *out=(cartpos_reference_t){.raw_um=position};return true; }
bool cartpos_apply_reference(const cartpos_reference_t *r,int64_t target) { (void)r;(void)target;referenced=true;return true; }
bool cartpos_reference_is_valid(void) { return referenced; }
bool cartpower_ready(void) { return power; }
int64_t cartpos_position_um(void) { return position; }
void cartpos_set_origin_mm(float x) { position=(long)(x*1000); }
bool cartpos_is_ok(void) { return true; }
bool poleang_is_ok(void) { return true; }
esp_err_t cartaxis_enable(bool on) { if(require_lock)assert(power_test_lock_depth==1);enabled=on;if(on && fail_at_enable) power=false;return ESP_OK; }
void cartaxis_set_position_um(long x) { (void)x; }
int64_t cartaxis_cmd_position_um(void) { return position; }
void cartaxis_set_vel_mm_s(long x) { assert(power_test_lock_depth==1);velocity=x; }
void cartaxis_halt(void) { assert(power_test_lock_depth==1);velocity=0; }
void cartaxis_stop(void) { assert(power_test_lock_depth==1);velocity=0;stops++; }
bool cartaxis_try_stop_at_rest(void) { assert(power_test_lock_depth==1);if(velocity!=0)return false;velocity=0;stops++;return true; }
bool cartaxis_peek_at_rest(void) { return true; }
bool cartaxis_at_rest(void) { return velocity==0; }
void cartaxis_set_accel_mm_s2(long x) { (void)x; }
void cartaxis_set_decel_mm_s2(long x) { (void)x; }
void cartaxis_set_wdt_ms(long x) { (void)x; }
void cartproto_register_exec(cartproto_exec_cb_t cb) { (void)cb; }
void cartproto_send_ok(const char *n,long v) { (void)n;(void)v; }
void cartproto_send_err(const char*n) { snprintf(reply,sizeof(reply),"ERR %s",n); }
void cartproto_send_mode(const char*m,const char*r) { snprintf(reply,sizeof(reply),"MODE %s %s",m,r); }
BaseType_t xTaskCreatePinnedToCore(void(*fn)(void*),const char*n,unsigned s,void*a,unsigned p,void*h,unsigned c) { (void)fn;(void)n;(void)s;(void)a;(void)p;(void)h;(void)c;return pdPASS; }
TickType_t xTaskGetTickCount(void) { return 0; }
void vTaskDelayUntil(TickType_t*p,TickType_t t) { (void)p;(void)t; }
static int64_t diag_clock;
int64_t esp_timer_get_time(void) { return ++diag_clock; }
bool cartpos_get_supervision(cartpos_supervision_t *out) {
    *out=(cartpos_supervision_t){.position_um=cartpos_position_um()}; return true;
}
void cartproto_send_raw(const char *data,int len) { (void)data;(void)len; }
#include "../components/cartfsm/cartfsm.c"
static void reset(void) { require_lock=false;s_started=false;s_mode=CM_DISABLED;s_reason=CR_NONE;s_calib=CAL_DONE;s_calib_l_um=850000;s_last_cmd_v=0;enabled=false;power=false;fail_at_enable=false;stops=0;velocity=0;position=0;reply[0]=0;assert(cartfsm_start()==ESP_OK);s_calib=CAL_DONE;referenced=true;require_lock=true; }
int main(void) {
    reset();exec_enable();assert(!enabled && !strcmp(reply,"ERR POWER"));
    power=true;s_calib=CAL_NONE;exec_enable();assert(!enabled && !strcmp(reply,"ERR ENABLE"));
    s_calib=CAL_DONE;exec_enable();assert(enabled && s_mode==CM_READY);
    exec_vel(50);assert(velocity==50);
    power=false;enter_power_fault();assert(!enabled && velocity==0 && s_reason==CR_POWER && !strcmp(reply,"MODE FAULT POWER"));
    exec_vel(100);assert(velocity==0);exec_reset();assert(s_mode==CM_DISABLED);exec_enable();assert(!enabled && !strcmp(reply,"ERR POWER"));
    reset();power=true;fail_at_enable=true;exec_enable();assert(!enabled && s_mode==CM_FAULT && s_reason==CR_POWER);
    reset();power=true;exec_enable();power=false;exec_vel(100);assert(velocity==0);enter_power_fault();assert(!enabled && stops>0);
    reset();power=true;exec_enable();enter_fault(CR_STEP_LOSS);
    assert(s_mode==CM_FAULT && s_fault_settling);exec_reset();exec_enable();
    assert(s_mode==CM_READY && enabled);settle_fault();assert(s_mode==CM_READY && enabled);
    exec_vel(50);enter_fault(CR_STEP_LOSS);settle_fault();assert(!enabled && s_mode==CM_FAULT);
    enter_fault(CR_AS5600);assert(s_reason==CR_STEP_LOSS);assert(power_test_lock_depth==0);
    reset();enter_power_fault();assert(s_mode==CM_DISABLED && !enabled);
    reset();power=true;s_calib=CAL_PENDING;exec_enable();assert(!enabled && !strcmp(reply,"ERR ENABLE"));
    exec_confirm_left();assert(s_calib==CAL_DONE && !enabled);power=false;exec_enable();assert(!enabled && !strcmp(reply,"ERR POWER"));
    power=true;exec_enable();assert(enabled);enter_power_fault();exec_reset();referenced=false;exec_enable();assert(!enabled && s_calib==CAL_PENDING);
    cart_req_t disable_req;assert(cartproto_parse_line("DISABLE",&disable_req));
    reset();exec_cmd(&disable_req);assert(s_mode==CM_DISABLED && !enabled && !strcmp(reply,"MODE DISABLED NONE"));
    power=true;exec_enable();exec_vel(50);exec_cmd(&disable_req);assert(s_mode==CM_READY && enabled && velocity==50 && !strcmp(reply,"ERR BUSY"));
    exec_vel(0);exec_cmd(&disable_req);assert(s_mode==CM_DISABLED && !enabled && s_last_cmd_v==0 && s_calib==CAL_DONE);
    exec_vel(100);assert(velocity==0);exec_enable();assert(enabled && s_mode==CM_READY);
    enter_fault(CR_STEP_LOSS);exec_cmd(&disable_req);assert(s_mode==CM_FAULT && s_reason==CR_STEP_LOSS && s_fault_settling);
    power=false;enter_power_fault();exec_cmd(&disable_req);assert(s_reason==CR_POWER && !enabled);exec_reset();exec_cmd(&disable_req);exec_enable();assert(!enabled && !strcmp(reply,"ERR POWER"));
    puts("cartfsm_power_test: all cases passed");
}
