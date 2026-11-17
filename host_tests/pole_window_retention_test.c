/* Successful-window policy through injected read/clock and public sample snapshots. */
#include <assert.h>
#include <stdio.h>
#include "magnetic_encoder_impl.h"
static int64_t now;
static bool good;
static uint32_t angle;
int64_t esp_timer_get_time(void){return now;}
void vTaskDelay(TickType_t t){now+=t*1000;}
static int64_t clock_now(void *ctx){(void)ctx;return now;}
static int32_t counts(void *ctx){(void)ctx;return 2097152;}
static bool read_frame(void *ctx,uint32_t *r,uint8_t *s){(void)ctx;*r=angle;*s=0;return good;}
static void tick(magnetic_encoder_inst_t *inst,bool ok){now+=ME_SAMPLE_PERIOD_US;angle+=2;good=ok;assert(magnetic_encoder_sampler_sample_once(inst)==ok);}
static magnetic_encoder_sample_t snap(magnetic_encoder_inst_t *inst){magnetic_encoder_sample_t s;assert(magnetic_encoder_get_sample((void*)inst,&s));return s;}
static void fill(magnetic_encoder_inst_t *inst){for(int i=0;i<MAGNETIC_ENCODER_HIST_LEN;i++)tick(inst,true);assert(snap(inst).velocity_valid);}
int main(void){
 magnetic_encoder_impl_t ops={.read_frame=read_frame,.counts_per_rev=counts,.retain_velocity_window_on_failure=true};
 magnetic_encoder_inst_t pole;good=true;assert(magnetic_encoder_sampler_init(&pole,&ops,NULL,"pole",clock_now,NULL)==ESP_OK);tick(&pole,false);assert(!snap(&pole).velocity_valid);fill(&pole);
 magnetic_encoder_sample_t before=snap(&pole);tick(&pole,false);magnetic_encoder_sample_t bad=snap(&pole);
 assert(bad.velocity_valid && !bad.last_attempt_ok && bad.ok);
 assert(bad.velocity_counts_per_s==before.velocity_counts_per_s && bad.velocity_span_us==before.velocity_span_us);
 assert(bad.sampled_at_us==before.sampled_at_us && bad.sample_seq==before.sample_seq && bad.position_counts==before.position_counts && bad.raw_counts==before.raw_counts);
 assert(bad.failure_seq==before.failure_seq+1);
 tick(&pole,true);magnetic_encoder_sample_t after=snap(&pole);
 assert(after.velocity_valid && after.continuity_seq==before.continuity_seq);
 assert(after.position_counts==before.position_counts+4);
 assert(after.velocity_span_us==before.velocity_span_us+ME_SAMPLE_PERIOD_US);
 assert(after.velocity_counts_per_s==2000000/ME_SAMPLE_PERIOD_US);
 /* Retaining history never suppresses the ten-failure fault counter. */
 for(int i=0;i<10;i++){tick(&pole,false);if(i<9)assert(snap(&pole).velocity_valid);}
 assert(!snap(&pole).ok && !snap(&pole).velocity_valid);
 tick(&pole,true);assert(snap(&pole).ok && snap(&pole).velocity_valid);
 /* Read-side expiry uses the last success, not telemetry/read attempts. */
 before=snap(&pole);now=before.sampled_at_us+before.continuous_gap_us;
 assert(snap(&pole).velocity_valid);now++;assert(!snap(&pole).velocity_valid);
 /* Exceeding the permitted continuity gap clears history, even on a bad read. */
 before=snap(&pole);now+=before.continuous_gap_us;tick(&pole,false);tick(&pole,true);
 after=snap(&pole);assert(!after.velocity_valid && after.continuity_seq==before.continuity_seq+1);fill(&pole);
 /* Clock rollback on a failed read also clears the velocity window. */
 before=snap(&pole);now-=2*ME_SAMPLE_PERIOD_US;tick(&pole,false);now=before.sampled_at_us;tick(&pole,true);assert(!snap(&pole).velocity_valid);
 /* Existing default policy (cart) still rebuilds after one failed read. */
 ops.retain_velocity_window_on_failure=false;magnetic_encoder_inst_t cart;assert(magnetic_encoder_sampler_init(&cart,&ops,NULL,"cart",clock_now,NULL)==ESP_OK);fill(&cart);tick(&cart,false);tick(&cart,true);assert(!snap(&cart).velocity_valid);
 puts("pole-only successful window retention passed");
}
