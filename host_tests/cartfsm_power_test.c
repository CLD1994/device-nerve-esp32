/* 供电与停机命令单元测试：正常链接模式机，以协作者和公开命令驱动。 */
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include "cartfsm.h"
#include "tmc2209.h"
#include "esp_timer.h"
#include "cartpos.h"
#include "cartcal.h"
#include "cartaxis.h"
#include "cartproto.h"
#include "poleang.h"
#include "freertos/task.h"

int power_test_lock_depth;
static bool power, enabled, fail_at_enable, referenced, healthy=true, resting=true;
static bool stored=true, started;
static long velocity;
static int64_t position, command_position;
static unsigned stops;
static char reply[40];
static cartproto_exec_cb_t dispatch;
static void (*supervisor)(void *);
static void *supervisor_arg;
static void (*on_health_read)(void);
static jmp_buf tick_boundary;

esp_err_t cartcal_load(cartcal_record_t *out) {
    if (!stored) return ESP_FAIL;
    *out=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};return ESP_OK;
}
esp_err_t cartcal_save(const cartcal_record_t *r) { (void)r;return ESP_OK; }
float settings_units_per_rev(void) { return 40; }
bool cartpos_capture_reference(cartpos_reference_t *out) { *out=(cartpos_reference_t){.raw_um=position};return true; }
bool cartpos_apply_reference(const cartpos_reference_t *r,int64_t target) { (void)r;position=target;referenced=true;return true; }
bool cartpos_reference_is_valid(void) { return referenced; }
bool cartpower_ready(void) { return power; }
int64_t cartpos_position_um(void) { return position; }
bool cartpos_is_ok(void) {
    /* 用协作者调用点安排已注册命令，覆盖监督快照与命令的交错。 */
    void (*hook)(void)=on_health_read;on_health_read=NULL;if(hook)hook();return healthy;
}
bool poleang_is_ok(void) { return true; }
esp_err_t cartaxis_enable(bool on) { if(started)assert(power_test_lock_depth==1);enabled=on;if(on && fail_at_enable)power=false;return ESP_OK; }
void cartaxis_set_position_um(long x) { command_position=x; }
int64_t cartaxis_cmd_position_um(void) { return command_position; }
void cartaxis_set_vel_mm_s(long x) { assert(power_test_lock_depth==1);velocity=x;resting=x==0; }
void cartaxis_halt(void) { assert(power_test_lock_depth==1);velocity=0; /* 到速前保持实际运动状态。 */ }
void cartaxis_stop(void) { assert(power_test_lock_depth==1);velocity=0;resting=true;stops++; }
bool cartaxis_try_stop_at_rest(void) { assert(power_test_lock_depth==1);if(!resting)return false;velocity=0;stops++;return true; }
bool cartaxis_at_rest(void) { return resting; }
void cartaxis_set_accel_mm_s2(long x) { (void)x; }
void cartaxis_set_decel_mm_s2(long x) { (void)x; }
void cartaxis_set_wdt_ms(long x) { (void)x; }
void cartproto_register_exec(cartproto_exec_cb_t cb) { dispatch=cb; }
void cartproto_send_ok(const char *n,long v) { (void)v;snprintf(reply,sizeof(reply),"OK %s",n); }
void cartproto_send_err(const char*n) { snprintf(reply,sizeof(reply),"ERR %s",n); }
void cartproto_send_mode(const char*m,const char*r) { snprintf(reply,sizeof(reply),"MODE %s %s",m,r); }
BaseType_t xTaskCreatePinnedToCore(void(*fn)(void*),const char*n,unsigned s,void*a,unsigned p,void*h,unsigned c) {
    supervisor=fn;supervisor_arg=a;(void)n;(void)s;(void)p;(void)h;(void)c;return pdPASS;
}
TickType_t xTaskGetTickCount(void) { return 0; }
void vTaskDelayUntil(TickType_t*p,TickType_t t) { (void)p;(void)t;longjmp(tick_boundary,1); }
/* 诊断协作者只提供当前实测位置；详细快照字段由专用诊断测试覆盖。 */
static int64_t diag_clock;
int64_t esp_timer_get_time(void) { return ++diag_clock; }
bool cartpos_get_supervision(cartpos_supervision_t *out) {
    *out=(cartpos_supervision_t){.position_um=position};return true;
}
void cartproto_send_raw(const char *data,int len) { (void)data;(void)len;assert(power_test_lock_depth==0); }
static void tick(void) { if(setjmp(tick_boundary)==0)supervisor(supervisor_arg);assert(power_test_lock_depth==0); }
static void cmd(cart_cmd_t c) { cart_req_t r={.cmd=c};reply[0]=0;dispatch(&r);assert(power_test_lock_depth==0); }
static void vel(long v) { cart_req_t r={.cmd=CART_CMD_VEL,.v_mm_s=v};dispatch(&r);assert(power_test_lock_depth==0); }
static void state(cm_mode_t m,cm_reason_t r) { assert(cartfsm_mode()==m && cartfsm_reason()==r); }
static void confirm(void) { cmd(CART_CMD_CONFIRM_LEFT);assert(cartfsm_calib()==CAL_DONE);position=0; }
static void ready(void) { power=true;confirm();cmd(CART_CMD_ENABLE);assert(enabled);state(CM_READY,CR_NONE); }
static void boot(void) { assert(cartfsm_start()==ESP_OK);started=true;assert(dispatch && supervisor && !enabled);state(CM_DISABLED,CR_NONE); }
static void gates(void) {
    cmd(CART_CMD_ENABLE);assert(!enabled && !strcmp(reply,"ERR POWER"));
    power=true;cmd(CART_CMD_ENABLE);assert(!enabled && !strcmp(reply,"ERR ENABLE"));
    confirm();power=false;cmd(CART_CMD_ENABLE);assert(!enabled && !strcmp(reply,"ERR POWER"));
    power=true;cmd(CART_CMD_ENABLE);vel(50);assert(velocity==50);
    power=false;vel(100);assert(velocity!=100);tick();
    state(CM_FAULT,CR_POWER);assert(!enabled && velocity==0 && stops>0 && !strcmp(reply,"MODE FAULT POWER"));
    vel(100);assert(velocity==0);cmd(CART_CMD_RESET);state(CM_DISABLED,CR_NONE);
    cmd(CART_CMD_ENABLE);assert(!enabled && !strcmp(reply,"ERR POWER"));
    tick();state(CM_DISABLED,CR_NONE);
    power=true;referenced=false;cmd(CART_CMD_ENABLE);assert(!enabled && cartfsm_calib()==CAL_PENDING);
}
static void enable_drop(void) { power=true;confirm();fail_at_enable=true;cmd(CART_CMD_ENABLE);state(CM_FAULT,CR_POWER);assert(!enabled && velocity==0); }
static void reset_enable(void) { cmd(CART_CMD_RESET);cmd(CART_CMD_ENABLE);state(CM_READY,CR_NONE);assert(enabled); }
static void fault_recovery(void) {
    ready();vel(50);command_position+=10000;tick();state(CM_FAULT,CR_STEP_LOSS);assert(enabled && velocity==0 && !resting);
    cmd(CART_CMD_DISABLE);state(CM_FAULT,CR_STEP_LOSS);assert(enabled);
    /* 监督已读到 FAULT 后，命令先完成 RESET/ENABLE；旧收尾不得禁用新 READY。 */
    on_health_read=reset_enable;tick();state(CM_READY,CR_NONE);assert(enabled);
    vel(50);command_position+=10000;tick();state(CM_FAULT,CR_STEP_LOSS);
    healthy=false;tick();state(CM_FAULT,CR_STEP_LOSS);assert(enabled);
    resting=true;tick();state(CM_FAULT,CR_STEP_LOSS);assert(!enabled && !strcmp(reply,"MODE FAULT STEP_LOSS"));
    power=false;tick();state(CM_FAULT,CR_POWER);assert(!enabled);
    cmd(CART_CMD_DISABLE);state(CM_FAULT,CR_POWER);
    cmd(CART_CMD_RESET);cmd(CART_CMD_DISABLE);cmd(CART_CMD_ENABLE);assert(!enabled && !strcmp(reply,"ERR POWER"));
}
static void power_during_settling(void) {
    ready();vel(50);command_position+=10000;tick();
    state(CM_FAULT,CR_STEP_LOSS);assert(enabled && !resting);
    unsigned before=stops;power=false;tick();
    state(CM_FAULT,CR_POWER);assert(!enabled && resting && stops>before && velocity==0);
}
static void reset_only(void) { cmd(CART_CMD_RESET);state(CM_DISABLED,CR_NONE); }
static void stale_power_snapshot(void) {
    ready();command_position+=10000;tick();state(CM_FAULT,CR_STEP_LOSS);
    power=false;on_health_read=reset_only;tick();
    state(CM_DISABLED,CR_NONE);assert(!enabled);
    cmd(CART_CMD_ENABLE);assert(!enabled && !strcmp(reply,"ERR POWER"));
}
static void disable(void) {
    cmd(CART_CMD_DISABLE);assert(!enabled && !strcmp(reply,"MODE DISABLED NONE"));
    ready();vel(50);cmd(CART_CMD_DISABLE);state(CM_READY,CR_NONE);assert(enabled && velocity==50 && !strcmp(reply,"ERR BUSY"));
    vel(0);cmd(CART_CMD_DISABLE);state(CM_DISABLED,CR_NONE);assert(!enabled && cartfsm_calib()==CAL_DONE);
    vel(100);assert(velocity==0);cmd(CART_CMD_ENABLE);state(CM_READY,CR_NONE);assert(enabled);
}
int main(int argc,char **argv) {
    assert(argc==2);stored=strcmp(argv[1],"missing")!=0;boot();
    if(!strcmp(argv[1],"gates"))gates();
    else if(!strcmp(argv[1],"enable-drop"))enable_drop();
    else if(!strcmp(argv[1],"fault-recovery"))fault_recovery();
    else if(!strcmp(argv[1],"disable"))disable();
    else if(!strcmp(argv[1],"power-settling"))power_during_settling();
    else if(!strcmp(argv[1],"stale-power"))stale_power_snapshot();
    else { assert(!stored);power=true;cmd(CART_CMD_ENABLE);assert(!enabled && cartfsm_calib()==CAL_NONE && !strcmp(reply,"ERR ENABLE")); }
    printf("cartfsm power (%s): all assertions passed\n",argv[1]);
}

/* TMC 查询的协作者；本套件不发起诊断，诊断行为由独立套件覆盖。 */
bool tmc2209_read_reg(uint8_t reg, uint32_t *out) { (void)reg; (void)out; assert(!"unexpected TMC query"); return false; }
bool cartaxis_peek_at_rest(void) { return resting; }
