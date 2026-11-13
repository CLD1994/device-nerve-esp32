/* cartfsm 命令单元测试；所有硬件、采样、存储和任务协作者均为替身。 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "cartcal.h"
#include "cartfsm.h"
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
static bool tmc_read_ok=true, stopped=true;
bool tmc2209_read_reg(uint8_t reg,uint32_t *out) { assert(power_test_lock_depth==1);tmc_reads++;*out=reg;return tmc_read_ok; }
bool cartpower_ready(void) { return true; }
static cartcal_record_t disk;
static esp_err_t load_error, save_error;
static bool healthy=true, referenced, apply_ok=true, enabled;
static int64_t raw, offset, command_pos, during_save_move;
static float scale=40;
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
bool cartaxis_peek_at_rest(void) { return stopped; }
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

static void cmd(cart_cmd_t c) { cart_req_t q={.cmd=c};reply[0]=0;dispatch(&q); }
int main(void) {
 cart_req_t parsed;
 assert(cartproto_parse_line("TMC?",&parsed) && parsed.cmd==CART_CMD_TMC_QUERY);
 assert(!cartproto_parse_line("TMC? 1",&parsed));
 disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};load_error=ESP_OK;
 assert(cartfsm_start()==ESP_OK);
 cmd(CART_CMD_TMC_QUERY);assert(tmc_reads==5 && !enabled && cartfsm_mode()==CM_DISABLED);
 assert(strstr(diag_output,"TMC1 GCONF 1 0 ") && strstr(diag_output,"TMC1 END\n"));
 tmc_read_ok=false;diag_output[0]=0;diag_output_len=0;cmd(CART_CMD_TMC_QUERY);
 assert(tmc_reads==10 && strstr(diag_output,"TMC1 GCONF 0 "));
 stopped=false;cmd(CART_CMD_TMC_QUERY);assert(tmc_reads==10 && !strcmp(reply,"ERR TMC_BUSY"));stopped=true;
 cmd(CART_CMD_CONFIRM_LEFT);cmd(CART_CMD_ENABLE);assert(cartfsm_mode()==CM_READY);
 cmd(CART_CMD_TMC_QUERY);assert(tmc_reads==10 && !strcmp(reply,"ERR TMC_BUSY"));
 puts("TMC readonly public dispatch: OK");return 0;
}
