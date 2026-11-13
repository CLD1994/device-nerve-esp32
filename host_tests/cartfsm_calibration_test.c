/* cartfsm 命令单元测试；所有硬件、采样、存储和任务协作者均为替身。 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
#include "cartfsm.h"
#include "cartcal.h"
#include "cartpos.h"
#include "cartaxis.h"
#include "cartproto.h"
#include "settings.h"
#include "poleang.h"
#include "freertos/task.h"
static void (*supervisor)(void *);
static void *supervisor_arg;
static jmp_buf tick_boundary;
BaseType_t xTaskCreatePinnedToCore(void(*fn)(void*),const char*n,unsigned s,void*a,unsigned p,void*h,unsigned c) { supervisor=fn;supervisor_arg=a;(void)n;(void)s;(void)p;(void)h;(void)c;return pdPASS; }
TickType_t xTaskGetTickCount(void) { return 0; }
void vTaskDelayUntil(TickType_t*p,TickType_t t) { (void)p;(void)t;longjmp(tick_boundary,1); }

int power_test_lock_depth;
bool cartpower_ready(void) { return true; }
static cartcal_record_t disk;
static esp_err_t load_error, save_error;
static bool healthy, referenced, apply_ok, enabled;
static unsigned vel_writes;
static long last_velocity;
static int64_t raw, offset, command_pos, during_save_move;
static float scale;
static cartpos_reference_t sample_ref;
static char reply[32];
static long reply_value;
static cartproto_exec_cb_t dispatch;
esp_err_t cartcal_load(cartcal_record_t *out) { if (load_error) return load_error; *out=disk; return ESP_OK; }
esp_err_t cartcal_save(const cartcal_record_t *r) { if (save_error) return save_error; disk=*r; raw+=during_save_move; return ESP_OK; }
float settings_units_per_rev(void) { return scale; }
bool cartpos_capture_reference(cartpos_reference_t *out) { if (!healthy) return false; *out=sample_ref;out->raw_um=raw; return true; }
bool cartpos_apply_reference(const cartpos_reference_t *r,int64_t target) { if (!apply_ok) return false; offset=r->raw_um-target;referenced=true;return true; }
bool cartpos_reference_is_valid(void) { return referenced && healthy; }
int64_t cartpos_position_um(void) { return raw-offset; }
bool cartpos_is_ok(void) { return healthy; }
bool poleang_is_ok(void) { return true; }
esp_err_t cartaxis_enable(bool on) { enabled=on; return ESP_OK; }
void cartaxis_set_position_um(long x) { command_pos=x; }
int64_t cartaxis_cmd_position_um(void) { return command_pos; }
void cartaxis_set_vel_mm_s(long v) { last_velocity=v; vel_writes++; }
void cartaxis_halt(void) { }
void cartaxis_stop(void) { }
bool cartaxis_try_stop_at_rest(void) { return true; }
bool cartaxis_at_rest(void) { return true; }
void cartaxis_set_accel_mm_s2(long x) { (void)x; }
void cartaxis_set_decel_mm_s2(long x) { (void)x; }
void cartaxis_set_wdt_ms(long x) { (void)x; }
void cartproto_register_exec(cartproto_exec_cb_t cb) { dispatch=cb; }
void cartproto_send_ok(const char *name,long value) { snprintf(reply,sizeof(reply),"OK %s",name);reply_value=value; }
void cartproto_send_err(const char *name) { snprintf(reply,sizeof(reply),"ERR %s",name); }
void cartproto_send_mode(const char *mode,const char *reason) { (void)reason;snprintf(reply,sizeof(reply),"MODE %s",mode); }

/* 调度替身在任务公开注册点接管执行，到第一次等待即返回；不模拟RTOS并发。 */
static void supervise_once(void) {
    assert(supervisor);
    if (setjmp(tick_boundary)==0) supervisor(supervisor_arg);
    assert(power_test_lock_depth==0);
}
static void boot(void) {
    referenced=false;enabled=false;offset=0;raw=0;healthy=true;apply_ok=true;
    during_save_move=0;save_error=ESP_OK;reply[0]=0;scale=40;
    memset(&sample_ref,0,sizeof(sample_ref));
    assert(cartfsm_start()==ESP_OK);
    assert(dispatch && supervisor);
    assert(cartfsm_mode()==CM_DISABLED && !enabled);
}
static void cmd(cart_cmd_t c) { cart_req_t q={.cmd=c};reply[0]=0;dispatch(&q); }
static void velocity(int32_t v) { cart_req_t q={.cmd=CART_CMD_VEL,.v_mm_s=v};dispatch(&q); }
static void config(const char *name,long value) { cart_req_t q={.cmd=CART_CMD_CONFIG_SET,.value=value};snprintf(q.name,sizeof(q.name),"%s",name);dispatch(&q); }
static void stored_track(void) {
    load_error=ESP_OK;
    disk=(cartcal_record_t){.length_um=853437,.pole_zero_urad=456,.pole_inv=1,.mm_per_rev=40};
}
static void missing_record(void) {
    load_error=ESP_FAIL;boot();
    cmd(CART_CMD_ENABLE);assert(!enabled && cartfsm_calib()==CAL_NONE);
    cmd(CART_CMD_CONFIRM_LEFT);assert(!strcmp(reply,"ERR CONFIRM_LEFT"));
}
static void invalid_record(void) {
    stored_track();disk.length_um=0;boot();
    assert(cartfsm_calib()==CAL_NONE);
    cmd(CART_CMD_CONFIRM_LEFT);assert(!referenced && !strcmp(reply,"ERR CONFIRM_LEFT"));
}
static void valid_record(void) {
    stored_track();boot();
    assert(cartfsm_calib()==CAL_PENDING && fw_params()->pole_zero_urad==456 && fw_params()->pole_inv==1);
    cmd(CART_CMD_ENABLE);assert(!enabled);
    healthy=false;cmd(CART_CMD_CONFIRM_LEFT);assert(cartfsm_calib()==CAL_PENDING && !referenced);
    healthy=true;raw=100000;cmd(CART_CMD_CONFIRM_LEFT);
    assert(cartfsm_calib()==CAL_DONE && !enabled && cartpos_position_um()==-426718 && command_pos==-426718);
    raw+=5000;cmd(CART_CMD_ENABLE);assert(enabled && command_pos==cartpos_position_um());
    cmd(CART_CMD_CONFIRM_LEFT);assert(!strcmp(reply,"ERR CONFIRM_LEFT"));
    unsigned writes=vel_writes;
    referenced=false;
    velocity(100);assert(vel_writes==writes); /* 监督拍之前也禁止非零速度。 */
    velocity(0);assert(vel_writes==writes+1 && last_velocity==0);
    assert(cartfsm_mode()==CM_READY && !referenced);
    supervise_once();assert(cartfsm_mode()==CM_FAULT && cartfsm_reason()==CR_AS5600);
    writes=vel_writes;velocity(0);
    assert(cartfsm_mode()==CM_FAULT && vel_writes==writes);
    cmd(CART_CMD_RESET);assert(cartfsm_mode()==CM_DISABLED && cartfsm_calib()==CAL_PENDING && !enabled);
    cmd(CART_CMD_CONFIRM_LEFT);cmd(CART_CMD_ENABLE);
    command_pos+=10000;supervise_once(); /* 指令位置偏差触发真实丢步监督。 */
    assert(cartfsm_mode()==CM_FAULT && cartfsm_reason()==CR_STEP_LOSS);
    cmd(CART_CMD_RESET);assert(cartfsm_mode()==CM_DISABLED && cartfsm_calib()==CAL_DONE && !enabled);
    referenced=false;cmd(CART_CMD_ENABLE);assert(!enabled && cartfsm_calib()==CAL_PENDING);
    scale=41;cmd(CART_CMD_CONFIRM_LEFT);assert(!referenced);cmd(CART_CMD_ENABLE);assert(!enabled);
    scale=40;
    save_error=ESP_FAIL;cmd(CART_CMD_MARK_LEFT);
    assert(cartfsm_calib()!=CAL_LEFT && disk.length_um==853437 && !strcmp(reply,"ERR CAL_STORAGE"));
    save_error=ESP_OK;raw=12345;cmd(CART_CMD_MARK_LEFT);assert(cartfsm_calib()==CAL_LEFT && disk.length_um==0);
    raw+=99999;cmd(CART_CMD_MARK_RIGHT);assert(cartfsm_calib()==CAL_LEFT && disk.length_um==0);
    int64_t old_position=cartpos_position_um();
    raw=12345+900000;old_position+=900000-99999;
    save_error=ESP_FAIL;cmd(CART_CMD_MARK_RIGHT);
    assert(cartfsm_calib()==CAL_LEFT && disk.length_um==0 && cartpos_position_um()==old_position);
    save_error=ESP_OK;during_save_move=150;cmd(CART_CMD_MARK_RIGHT);
    assert(cartfsm_calib()==CAL_DONE && disk.length_um==900000 && cartpos_position_um()==450150 && command_pos==450150);
    during_save_move=0;
    long old=fw_params()->pole_zero_urad;
    save_error=ESP_FAIL;config("POLE_ZERO_URAD",123);assert(fw_params()->pole_zero_urad==old);
    save_error=ESP_OK;config("POLE_ZERO_URAD",123);assert(disk.pole_zero_urad==123 && fw_params()->pole_zero_urad==123);
    config("POLE_INV",2);assert(!strcmp(reply,"ERR POLE_INV"));
    cmd(CART_CMD_MARK_LEFT);raw+=500000;apply_ok=false;cmd(CART_CMD_MARK_RIGHT);
    assert(cartfsm_calib()==CAL_PENDING && disk.length_um==500000 && !strcmp(reply,"ERR CAL_REFERENCE"));
    apply_ok=true;raw=0;cmd(CART_CMD_CONFIRM_LEFT);assert(cartfsm_calib()==CAL_DONE);
    for (int i=0;i<3;i++) {
        raw=10000;cmd(CART_CMD_MARK_LEFT);raw+=500000;
        if(i==0) sample_ref.failure_seq++;
        if(i==1) sample_ref.continuity_seq++;
        if(i==2) sample_ref.scale_revision++;
        referenced=false; /* 采样协作者报告本轮位置参考失效。 */
        cmd(CART_CMD_MARK_RIGHT);
        assert(!strcmp(reply,"ERR CAL_REFERENCE") && disk.length_um==0 && !referenced);
        cmd(CART_CMD_ENABLE);assert(!enabled);
        raw=10000;cmd(CART_CMD_MARK_LEFT);raw+=500000;cmd(CART_CMD_MARK_RIGHT);
        assert(cartfsm_calib()==CAL_DONE && disk.length_um==500000);
    }
    healthy=false;cmd(CART_CMD_MARK_LEFT);
    assert(cartfsm_calib()==CAL_NONE && disk.length_um==0 && !strcmp(reply,"ERR MARK_LEFT"));
    healthy=true;referenced=false;cmd(CART_CMD_CONFIRM_LEFT);assert(!referenced);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"missing")) missing_record();
    else if(!strcmp(argv[1],"invalid")) invalid_record();
    else { assert(!strcmp(argv[1],"valid"));valid_record(); }
    printf("cartfsm calibration (%s): all assertions passed\n",argv[1]);
}
