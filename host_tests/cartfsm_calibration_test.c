/* cartfsm 命令单元测试；所有硬件、采样、存储和任务协作者均为替身。 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "cartcal.h"
#include "cartpos.h"
#include "cartaxis.h"
#include "cartproto.h"
#include "settings.h"
#include "poleang.h"
#include "freertos/task.h"
BaseType_t xTaskCreatePinnedToCore(void(*fn)(void*),const char*n,unsigned s,void*a,unsigned p,void*h,unsigned c) { (void)fn;(void)n;(void)s;(void)a;(void)p;(void)h;(void)c;return pdPASS; }
TickType_t xTaskGetTickCount(void) { return 0; }
void vTaskDelayUntil(TickType_t*p,TickType_t t) { (void)p;(void)t; }

int power_test_lock_depth;
static unsigned tmc_reads;
static bool tmc_read_ok=true;
bool tmc2209_read_reg(uint8_t reg,uint32_t *out) { assert(power_test_lock_depth==1);tmc_reads++;*out=reg;return tmc_read_ok; }
bool cartpower_ready(void) { return true; }
static cartcal_record_t disk;
static esp_err_t load_error, save_error;
static bool healthy, referenced, apply_ok, enabled;
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
void cartaxis_set_vel_mm_s(long v) { (void)v; }
void cartaxis_halt(void) { }
void cartaxis_stop(void) { }
bool cartaxis_try_stop_at_rest(void) { return true; }
bool cartaxis_peek_at_rest(void) { return true; }
bool cartaxis_at_rest(void) { return true; }
void cartaxis_set_accel_mm_s2(long x) { (void)x; }
void cartaxis_set_decel_mm_s2(long x) { (void)x; }
void cartaxis_set_wdt_ms(long x) { (void)x; }
void cartproto_register_exec(cartproto_exec_cb_t cb) { dispatch=cb; }
void cartproto_send_ok(const char *name,long value) { snprintf(reply,sizeof(reply),"OK %s",name);reply_value=value; }
void cartproto_send_err(const char *name) { snprintf(reply,sizeof(reply),"ERR %s",name); }
void cartproto_send_mode(const char *mode,const char *reason) { (void)reason;snprintf(reply,sizeof(reply),"MODE %s",mode); }
static char diag_output[2048];
static size_t diag_output_len;
static int64_t diag_clock;
int64_t esp_timer_get_time(void) { return ++diag_clock; }
void cartproto_send_raw(const char *data,int len) {
 assert(power_test_lock_depth==0);
 assert(len>0 && diag_output_len+(size_t)len<sizeof(diag_output));
 memcpy(diag_output+diag_output_len,data,(size_t)len);
 diag_output_len+=(size_t)len;diag_output[diag_output_len]=0;
}
#include "../components/cartfsm/cartfsm.c"
static void boot(void) {
    s_started=false;s_mode=CM_DISABLED;s_reason=CR_NONE;s_calib=CAL_NONE;
    referenced=false;enabled=false;offset=0;raw=0;healthy=true;apply_ok=true;
    during_save_move=0;save_error=ESP_OK;reply[0]=0;scale=40;
    memset(&sample_ref,0,sizeof(sample_ref));
    assert(cartfsm_start()==ESP_OK);
}
static void cmd(cart_cmd_t c) { cart_req_t q={.cmd=c};reply[0]=0;dispatch(&q); }
static void config(const char *name,long value) { cart_req_t q={.cmd=CART_CMD_CONFIG_SET,.value=value};snprintf(q.name,sizeof(q.name),"%s",name);dispatch(&q); }
int main(void) {
    load_error=ESP_FAIL;boot();cmd(CART_CMD_ENABLE);assert(!enabled && s_calib==CAL_NONE);
    cmd(CART_CMD_CONFIRM_LEFT);assert(!strcmp(reply,"ERR CONFIRM_LEFT"));
    load_error=ESP_OK;disk=(cartcal_record_t){.length_um=853437,.pole_zero_urad=123,.pole_inv=1,.mm_per_rev=40};boot();
    assert(s_calib==CAL_PENDING && fw_params()->pole_zero_urad==123 && fw_params()->pole_inv==1);
    cmd(CART_CMD_ENABLE);assert(!enabled);
    healthy=false;cmd(CART_CMD_CONFIRM_LEFT);assert(s_calib==CAL_PENDING && !referenced);
    healthy=true;raw=100000;cmd(CART_CMD_CONFIRM_LEFT);assert(s_calib==CAL_DONE && !enabled && cartpos_position_um()==-426718 && command_pos==-426718);
    raw+=5000;cmd(CART_CMD_ENABLE);assert(enabled && command_pos==cartpos_position_um());
    cmd(CART_CMD_CONFIRM_LEFT);assert(!strcmp(reply,"ERR CONFIRM_LEFT"));
    s_mode=CM_FAULT;cmd(CART_CMD_RESET);assert(s_mode==CM_DISABLED && s_calib==CAL_DONE && !enabled);
    s_mode=CM_FAULT;referenced=false;cmd(CART_CMD_RESET);assert(s_calib==CAL_PENDING);
    boot();cmd(CART_CMD_CONFIRM_LEFT);referenced=false;cmd(CART_CMD_ENABLE);assert(!enabled && s_calib==CAL_PENDING);
    boot();scale=41;cmd(CART_CMD_CONFIRM_LEFT);assert(!referenced);cmd(CART_CMD_ENABLE);assert(!enabled);
    boot();save_error=ESP_FAIL;cmd(CART_CMD_MARK_LEFT);assert(s_calib!=CAL_LEFT && disk.length_um==853437 && !strcmp(reply,"ERR CAL_STORAGE"));
    save_error=ESP_OK;raw=12345;cmd(CART_CMD_MARK_LEFT);assert(s_calib==CAL_LEFT && disk.length_um==0);
    raw+=99999;cmd(CART_CMD_MARK_RIGHT);assert(s_calib==CAL_LEFT && disk.length_um==0);
    raw=12345+900000;save_error=ESP_FAIL;cmd(CART_CMD_MARK_RIGHT);assert(s_calib==CAL_LEFT && disk.length_um==0 && offset==0);
    save_error=ESP_OK;during_save_move=150;cmd(CART_CMD_MARK_RIGHT);assert(s_calib==CAL_DONE && disk.length_um==900000 && cartpos_position_um()==450150 && command_pos==450150);
    boot();assert(s_calib==CAL_PENDING && !enabled);
    long old=fw_params()->pole_zero_urad;save_error=ESP_FAIL;config("POLE_ZERO_URAD",456);assert(fw_params()->pole_zero_urad==old);
    save_error=ESP_OK;config("POLE_ZERO_URAD",456);assert(disk.pole_zero_urad==456);boot();assert(fw_params()->pole_zero_urad==456);
    config("POLE_INV",2);assert(!strcmp(reply,"ERR POLE_INV"));
    cmd(CART_CMD_MARK_LEFT);raw+=500000;apply_ok=false;cmd(CART_CMD_MARK_RIGHT);assert(s_calib==CAL_PENDING && disk.length_um==500000 && !strcmp(reply,"ERR CAL_REFERENCE"));
    apply_ok=true;raw=0;cmd(CART_CMD_CONFIRM_LEFT);assert(s_calib==CAL_DONE);
    for (int i=0;i<3;i++) {
        boot();raw=10000;cmd(CART_CMD_MARK_LEFT);raw+=500000;
        if (i==0) sample_ref.failure_seq++;
        if (i==1) sample_ref.continuity_seq++;
        if (i==2) sample_ref.scale_revision++;
        cmd(CART_CMD_MARK_RIGHT);
        assert(!strcmp(reply,"ERR CAL_REFERENCE") && disk.length_um==0 && !referenced);
        cmd(CART_CMD_ENABLE);assert(!enabled);
        raw=10000;cmd(CART_CMD_MARK_LEFT);raw+=500000;cmd(CART_CMD_MARK_RIGHT);
        assert(s_calib==CAL_DONE && disk.length_um==500000);
    }
    boot();healthy=false;cmd(CART_CMD_MARK_LEFT);
    assert(s_calib==CAL_NONE && disk.length_um==0 && !strcmp(reply,"ERR MARK_LEFT"));
    boot();assert(s_calib==CAL_NONE);cmd(CART_CMD_CONFIRM_LEFT);assert(!referenced);
    puts("cartfsm calibration: all assertions passed");
    return 0;
}
