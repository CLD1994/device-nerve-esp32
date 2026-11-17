#include <assert.h>
#include <stdio.h>
#include "magnetic_encoder_impl.h"
static int64_t now;
int64_t esp_timer_get_time(void){return now;}
void vTaskDelay(TickType_t t){now+=t*1000;}
static int64_t clk(void *c){(void)c;return now;}
static int32_t cpr(void*c){(void)c;return 2097152;}
static bool good=true, rearm=false;
static magnetic_encoder_inst_t inst;
static bool read_frame(void*c,uint32_t*r,uint8_t*s){(void)c;*r=12;*s=0;if(rearm){inst.ops.diagnostic_arm((void*)&inst,99);rearm=false;}return good;}
static void failure(void*c,me_diag_failure_t*f){(void)c;f->kind=3;f->frame[5]=123;}
static void step(void){now+=1000;magnetic_encoder_sampler_sample_once(&inst);}
static void fill(void){good=true;for(int i=0;i<MAGNETIC_ENCODER_HIST_LEN;i++)step();}
int main(void){
 magnetic_encoder_impl_t ops={.read_frame=read_frame,.counts_per_rev=cpr,.failure_snapshot=failure};
 assert(magnetic_encoder_sampler_init(&inst,&ops,0,"pole",clk,0)==ESP_OK);
 magnetic_encoder_handle_t h=(void*)&inst; me_diag_t d; magnetic_encoder_sample_t sample;
 fill(); h->diagnostic_get(h,&d); assert(!d.captured);
 h->diagnostic_arm(h,1);fill();
 assert(inst.ops.diagnostic_arm && inst.ops.diagnostic_get);
 good=false;step();h->diagnostic_get(h,&d);
 assert(d.captured && d.before.valid && !d.after.valid && (d.after.reason&2));
 assert(d.before.fill==MAGNETIC_ENCODER_HIST_LEN && d.after.fill==0);
 assert(d.first_failure.kind==3 && d.first_failure.frame[5]==123 && d.first_failure.seq==d.after.failure_seq);
 uint64_t seq=d.after.failure_seq;step();h->diagnostic_get(h,&d);assert(d.after.failure_seq==seq);
 h->diagnostic_arm(h,5);fill();now+=20001;assert(magnetic_encoder_get_sample(h,&sample));
 h->diagnostic_get(h,&d);assert(d.run_id==5 && d.captured && (d.after.reason&32) && !d.has_failure);
 h->diagnostic_arm(h,6);fill();rearm=true;good=false;step();
 h->diagnostic_get(h,&d);assert(d.run_id==99 && !d.captured && !d.ready && d.failure.seq==0);
 assert(magnetic_encoder_get_sample(h,&sample));h->diagnostic_get(h,&d);assert(!d.captured);
 fill();good=false;step();h->diagnostic_get(h,&d);assert(d.captured);
 puts("pole diagnostic sampling passed");
}
