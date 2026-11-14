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
void (*supervisor)(void *);
void *supervisor_arg;
jmp_buf tick_boundary;
BaseType_t xTaskCreatePinnedToCore(void(*fn)(void*),const char*n,unsigned s,void*a,unsigned p,void*h,unsigned c) { supervisor=fn;supervisor_arg=a;(void)n;(void)s;(void)p;(void)h;(void)c;return pdPASS; }
TickType_t xTaskGetTickCount(void) { return 0; }
void vTaskDelayUntil(TickType_t*p,TickType_t t) { (void)p;(void)t;longjmp(tick_boundary,1); }

int power_test_lock_depth;
bool power_ready=true;
bool cartpower_ready(void) { return power_ready; }
cartcal_record_t disk;
esp_err_t load_error, save_error;
bool healthy, referenced, apply_ok, enabled;
unsigned vel_writes;
long last_velocity;
int64_t raw, offset, command_pos, during_save_move;
float scale;
cartpos_reference_t sample_ref;
char reply[32];
long reply_value;
cartproto_exec_cb_t dispatch;
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
unsigned halt_calls;
long last_accel;
void cartaxis_halt(void) { halt_calls++; }
void cartaxis_stop(void) { }
bool cartaxis_try_stop_at_rest(void) { return true; }
bool axis_rest=true;
bool cartaxis_at_rest(void) { return axis_rest; }
void cartaxis_set_accel_mm_s2(long x) { last_accel=x; }
void cartaxis_set_decel_mm_s2(long x) { (void)x; }
void cartaxis_set_wdt_ms(long x) { (void)x; }
void cartproto_register_exec(cartproto_exec_cb_t cb) { dispatch=cb; }
void cartproto_send_ok(const char *name,long value) { snprintf(reply,sizeof(reply),"OK %s",name);reply_value=value; }
void cartproto_send_err(const char *name) { snprintf(reply,sizeof(reply),"ERR %s",name); }
void cartproto_send_mode(const char *mode,const char *reason) { (void)reason;snprintf(reply,sizeof(reply),"MODE %s",mode); }

int64_t diag_clock;
bool diag_snapshot_available=true, diag_use_snapshot;
cartpos_supervision_t diag_snapshot;
char diag_output[8192];
size_t diag_output_len;
unsigned diag_raw_sends, diag_snapshot_reads;
int64_t esp_timer_get_time(void) { return ++diag_clock; }
bool cartpos_get_supervision(cartpos_supervision_t *out) {
    diag_snapshot_reads++;
    if (!diag_snapshot_available) return false;
    *out=diag_use_snapshot ? diag_snapshot
        : (cartpos_supervision_t){.position_um=cartpos_position_um()}; return true;
}
void cartproto_send_raw(const char *data,int len) {
    assert(power_test_lock_depth==0); /* 格式化后的发送不持有输出锁。 */
    assert(len>0 && diag_output_len+(size_t)len<sizeof(diag_output));
    memcpy(diag_output+diag_output_len,data,(size_t)len);
    diag_output_len+=(size_t)len; diag_output[diag_output_len]=0; diag_raw_sends++;
}

/* 调度替身在任务公开注册点接管执行，到第一次等待即返回；不模拟RTOS并发。 */
void supervise_once(void) {
    assert(supervisor);
    if (setjmp(tick_boundary)==0) supervisor(supervisor_arg);
    assert(power_test_lock_depth==0);
}
void boot(void) {
    referenced=false;enabled=false;offset=0;raw=0;healthy=true;apply_ok=true;
    during_save_move=0;save_error=ESP_OK;reply[0]=0;scale=40;
    memset(&sample_ref,0,sizeof(sample_ref));
    assert(cartfsm_start()==ESP_OK);
    assert(dispatch && supervisor);
    assert(cartfsm_mode()==CM_DISABLED && !enabled);
}
void cmd(cart_cmd_t c) { cart_req_t q={.cmd=c};reply[0]=0;dispatch(&q); }
void velocity(int32_t v) { cart_req_t q={.cmd=CART_CMD_VEL,.v_mm_s=v};dispatch(&q); }
void config(const char *name,long value) { cart_req_t q={.cmd=CART_CMD_CONFIG_SET,.value=value};snprintf(q.name,sizeof(q.name),"%s",name);dispatch(&q); }
