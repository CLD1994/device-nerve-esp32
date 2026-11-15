/* PCNT 边界替身：验证引擎诊断 API，不证明真实硬件计数能力。 */
#include <assert.h>
#include <stdint.h>
#include "step_engine.h"
#include "driver/pulse_cnt.h"
#include "driver/gpio.h"
static int unit, channel, count;
static bool enabled, running;
static int64_t now;
static esp_err_t read_error;
int64_t esp_timer_get_time(void) { return now; }
esp_err_t gpio_input_enable(gpio_num_t pin) { assert(pin == 21); return ESP_OK; }
int gpio_get_level(gpio_num_t pin) { assert(pin == 21); return 1; }
esp_err_t pcnt_new_unit(const pcnt_unit_config_t *c, pcnt_unit_handle_t *h)
{
    assert(c->low_limit == -30000 && c->high_limit == 30000 && c->flags.accum_count);
#ifdef PCNT_TEST_INIT_FAIL
    (void)h; return ESP_FAIL;
#else
    *h = &unit; return ESP_OK;
#endif
}
esp_err_t pcnt_new_channel(pcnt_unit_handle_t u,const pcnt_chan_config_t *c,pcnt_channel_handle_t *h)
{ assert(u == &unit && c->edge_gpio_num == 1 && c->level_gpio_num == 2); *h=&channel; return ESP_OK; }
esp_err_t pcnt_channel_set_edge_action(pcnt_channel_handle_t h,pcnt_channel_edge_action_t a,pcnt_channel_edge_action_t b)
{ assert(h==&channel && a==PCNT_CHANNEL_EDGE_ACTION_INCREASE && b==PCNT_CHANNEL_EDGE_ACTION_HOLD); return ESP_OK; }
esp_err_t pcnt_channel_set_level_action(pcnt_channel_handle_t h,pcnt_channel_level_action_t a,pcnt_channel_level_action_t b)
{ assert(h==&channel && a==PCNT_CHANNEL_LEVEL_ACTION_KEEP && b==PCNT_CHANNEL_LEVEL_ACTION_INVERSE); return ESP_OK; }
esp_err_t pcnt_unit_add_watch_point(pcnt_unit_handle_t h,int point)
{ assert(h==&unit && (point==30000 || point==-30000)); return ESP_OK; }
esp_err_t pcnt_unit_clear_count(pcnt_unit_handle_t h)
{ assert(h==&unit && !enabled && !running); count=0; return ESP_OK; }
esp_err_t pcnt_unit_enable(pcnt_unit_handle_t h) { assert(h==&unit); enabled=true; return ESP_OK; }
esp_err_t pcnt_unit_disable(pcnt_unit_handle_t h) { assert(h==&unit); enabled=false; return ESP_OK; }
esp_err_t pcnt_unit_start(pcnt_unit_handle_t h) { assert(h==&unit && enabled); running=true; return ESP_OK; }
esp_err_t pcnt_unit_stop(pcnt_unit_handle_t h) { assert(h==&unit); running=false; return ESP_OK; }
esp_err_t pcnt_unit_get_count(pcnt_unit_handle_t h,int *v) { assert(h==&unit); *v=count; return read_error; }
esp_err_t pcnt_del_channel(pcnt_channel_handle_t h) { assert(h==&channel); return ESP_OK; }
esp_err_t pcnt_del_unit(pcnt_unit_handle_t h) { assert(h==&unit); return ESP_OK; }
void step_pcnt_fake_verify(void)
{
    step_engine_diag_t d;
    step_engine_diag_snapshot(&d);
    assert(d.en_level==1 && d.en_read_error==ESP_OK);
#ifdef PCNT_TEST_INIT_FAIL
    assert(!d.pcnt_valid && d.pcnt_init_error==ESP_FAIL);
#else
    assert(d.pcnt_valid && d.pcnt_init_error==ESP_OK && running);
    count=123;
    step_engine_diag_snapshot(&d);
    assert(d.pcnt_valid && d.pcnt_count==123);
    count=-321;
    step_engine_set_position(0);
    step_engine_diag_snapshot(&d);
    assert(d.pcnt_valid && d.pcnt_count==-321);
    read_error=ESP_FAIL;
    step_engine_diag_snapshot(&d);
    assert(!d.pcnt_valid && d.pcnt_read_error==ESP_FAIL);
    read_error=ESP_OK;
    now=3600LL*1000000;
    step_engine_diag_snapshot(&d);
    assert(!d.pcnt_valid && d.pcnt_overflow_invalid && !running);
    now=0;
    step_engine_diag_snapshot(&d);
    assert(!d.pcnt_valid && d.pcnt_overflow_invalid);
#endif
}
