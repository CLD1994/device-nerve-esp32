/* 真实cartpower适配器，硬件/时钟/任务替身。无真实I2C或设备。 */
#include <assert.h>
#include <setjmp.h>
#include <math.h>
#include "ch224q.h"
#define POWER_CRITICAL_HOOK
#include "freertos/task.h"
#define CONFIG_CARTPOWER_SETTLE_MS 3000
#define CONFIG_CARTPOWER_TIMEOUT_MS 10000
#define CONFIG_CARTPOWER_SAMPLE_MS 100
#define CONFIG_CARTPOWER_STABLE_SAMPLES 5
#define CONFIG_CARTPOWER_FRESH_MS 500
#define CONFIG_CH224Q_I2C_ADDR 0x22
static int64_t now;
static bool publish_on_lock;
static int loops, write_count, drop_at;
static esp_err_t init_result, write_result, read_result;
static bool pd;
static float volts;
static void (*task)(void*);
static jmp_buf done;
int64_t esp_timer_get_time(void) { return now; }
esp_err_t ch224q_init(const ch224q_config_t *cfg,ch224q_handle_t *out) { assert(cfg->dev_addr==0x22);*out=(void*)1;return init_result; }
esp_err_t ch224q_set_voltage(ch224q_handle_t h,ch224q_vsel_t v) { (void)h;assert(v==CH224Q_VSEL_20V);write_count++;return write_result; }
esp_err_t ch224q_get_status(ch224q_handle_t h,ch224q_status_t *out) { (void)h;out->pd=pd;return read_result; }
float bsp_vbus_read_volt(void) { return volts; }
BaseType_t xTaskCreate(void (*fn)(void*),const char*n,unsigned s,void*a,unsigned p,void*h) { (void)n;(void)s;(void)a;(void)p;(void)h;task=fn;return pdPASS; }
void vTaskDelay(TickType_t t) { now+=(int64_t)t*1000;if(loops==drop_at)volts=9;if(++loops>=40)longjmp(done,1); }
void vTaskDelete(void *p) { (void)p; }
#include "../components/cartpower/cartpower.c"
void power_test_enter(void) { if(publish_on_lock) { publish_on_lock=false;now+=1000;s_core.last_sample_us=now; } }
static void reset(void) { s_started=false;s_core=(cp_core_t){.state=CP_FAILED,.reason=CP_INIT};now=0;loops=0;write_count=0;drop_at=-1;init_result=write_result=read_result=ESP_OK;pd=true;volts=20;task=NULL; }
static void run(void) { if(!setjmp(done)) task(NULL); }
int main(void) {
    reset();assert(!cartpower_ready());assert(cartpower_start((void*)1)==ESP_OK);assert(!cartpower_ready());run();assert(cartpower_ready());assert(write_count==1);
    publish_on_lock=true;assert(cartpower_ready());
    now+=500001;assert(!cartpower_ready());assert(s_core.reason==CP_STALE);assert(cartpower_start((void*)1)==ESP_ERR_INVALID_STATE);
    reset();write_result=ESP_FAIL;assert(cartpower_start((void*)1)==ESP_OK);run();assert(!cartpower_ready() && s_core.reason==CP_REQUEST);
    reset();init_result=ESP_FAIL;assert(cartpower_start((void*)1)==ESP_FAIL);assert(!cartpower_ready() && !task);
    reset();read_result=ESP_FAIL;cartpower_start((void*)1);run();assert(s_core.reason==CP_READ);
    reset();volts=NAN;cartpower_start((void*)1);run();assert(s_core.reason==CP_ADC);
    reset();drop_at=35;cartpower_start((void*)1);run();assert(s_core.reason==CP_VOLTAGE && write_count==1);
    reset();cartpower_start((void*)1);now=11000000;assert(!cartpower_ready());run();assert(write_count==0);
    puts("cartpower_adapter_test: all cases passed");
}
