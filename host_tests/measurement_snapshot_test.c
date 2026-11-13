/* 同快照解释与失败不覆盖：无硬件，getter替身刻意与snapshot不一致。 */
#include <assert.h>
#include <stdio.h>
#include "cartpos.h"
#include "poleang.h"
#include "params.h"
#include "settings.h"
#include "freertos/task.h"
static magnetic_encoder_sample_t sample;
static fw_params_t params;
static bool available = true;
static float upr = 40;
static settings_change_cb_t callback;
const fw_params_t *fw_params(void) { return &params; }
float settings_units_per_rev(void) { return upr; }
bool settings_subscribe(settings_change_cb_t cb) { callback=cb; return true; }
int64_t esp_timer_get_time(void) { return 1000000; }
void vTaskDelay(TickType_t ticks) { (void)ticks; }
static bool configure_gap(magnetic_encoder_handle_t h, int64_t gap)
{ (void)h; assert(gap == 5000 || gap == 5125); return true; }
static int32_t cpr(magnetic_encoder_handle_t h) { (void)h; return 4000; }
static int32_t vel(magnetic_encoder_handle_t h) { (void)h; assert(0); return 0; }
static bool get(magnetic_encoder_handle_t h, magnetic_encoder_sample_t *out)
{ (void)h; if (!available) return false; *out=sample; return true; }
static struct magnetic_encoder_s enc = { .set_continuous_gap_us=configure_gap, .counts_per_rev=cpr, .velocity_counts_per_s=vel, .get_sample=get };
int main(void) {
    cartpos_init(&enc, 2000); poleang_init(&enc);
    sample=(magnetic_encoder_sample_t){.continuous_gap_us=5000,.valid=true,.last_attempt_ok=true,.ok=true,
        .sampled_at_us=1000000,.sample_seq=42,.velocity_valid=true,.velocity_span_us=16000,
        .position_counts=2000,.raw_counts=1000,.velocity_counts_per_s=4000};
    cartpos_measurement_t cart={.x_um=123,.vx_mm_s=456};
    poleang_measurement_t pole={.theta_urad=123,.vth_mrad_s=456};
    assert(cartpos_get_measurement(&cart)); assert(cart.x_um==20000 && cart.vx_mm_s==40);
    assert(poleang_get_measurement(&pole)); assert(pole.theta_urad==1570796 && pole.vth_mrad_s==6283);
    cartpos_supervision_t supervision;
    assert(cartpos_get_supervision(&supervision));
    assert(supervision.position_um==20000 && supervision.sample.position_counts==2000);
    assert(supervision.velocity_mm_s==40 && supervision.sample.sampled_at_us==1000000);
    assert(cart.sampled_at_us==1000000 && cart.sample_seq==42 && cart.velocity_span_us==16000);
    assert(pole.sampled_at_us==1000000 && pole.sample_seq==42 && pole.velocity_span_us==16000);
    params.pole_inv=1;
    assert(poleang_get_measurement(&pole)); assert(pole.theta_urad==-1570796 && pole.vth_mrad_s==-6283);
    sample.velocity_valid=false;
    assert(cartpos_get_supervision(&supervision) && !supervision.sample.velocity_valid);
    assert(supervision.position_um==20000); /* 预热不改变位置监督判据。 */
    assert(!cartpos_get_measurement(&cart)); assert(cart.x_um==20000 && cart.vx_mm_s==40);
    assert(!poleang_get_measurement(&pole)); assert(pole.theta_urad==-1570796);
    sample.velocity_valid=true; available=false;
    assert(!cartpos_get_measurement(&cart)); assert(!poleang_get_measurement(&pole));
    available=true; sample.last_attempt_ok=false;
    assert(!cartpos_get_measurement(&cart)); assert(!poleang_get_measurement(&pole));
    sample.last_attempt_ok=true; upr=0; callback(SET_MM_PER_REV,0);
    assert(!cartpos_get_measurement(&cart));
    assert(!cartpos_get_measurement(NULL)); assert(!poleang_get_measurement(NULL));
    upr=40;
    cartpos_init(&enc, 0);
    assert(!cartpos_get_measurement(&cart));
    cartpos_init(&enc, 2000);
    assert(cartpos_get_measurement(&cart));
    puts("measurement snapshot passed");
}
