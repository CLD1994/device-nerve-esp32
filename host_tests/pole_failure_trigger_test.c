#include <assert.h>
#include <stdio.h>
#include "magnetic_encoder_impl.h"
#include "magnetic_encoder_failure_trigger.h"
static int64_t now;
int64_t esp_timer_get_time(void){return now;}
void vTaskDelay(TickType_t t){now+=t*1000;}
static int64_t clock_now(void *ctx){(void)ctx;return now;}
static int32_t counts(void *ctx){(void)ctx;return 2097152;}
typedef struct {bool good, returned, enabled;unsigned highs;me_failure_trigger_t trigger;} source_t;
static void raise_pin(void *ctx){source_t*s=ctx;assert(s->returned);s->highs++;}
static bool read_frame(void *ctx,uint32_t *r,uint8_t *status){source_t*s=ctx;s->returned=false;*r=120;*status=0;s->returned=true;return s->good;}
static void failed(void *ctx){source_t*s=ctx;assert(s->returned);if(s->enabled)me_failure_trigger_read_done(&s->trigger,false);}
static void valid(void *ctx,bool ok){source_t*s=ctx;if(s->enabled)me_failure_trigger_valid(&s->trigger,ok);}
static void step(magnetic_encoder_inst_t *inst){now+=1000;magnetic_encoder_sampler_sample_once(inst);}
int main(void){
    magnetic_encoder_impl_t ops={.read_frame=read_frame,.counts_per_rev=counts,.read_failed=failed,.measurement_valid=valid};
    source_t pole={.enabled=true};pole.trigger.raise=raise_pin;pole.trigger.context=&pole;
    magnetic_encoder_inst_t inst;
    assert(magnetic_encoder_sampler_init(&inst,&ops,&pole,"pole",clock_now,NULL)==ESP_OK);
    step(&inst);assert(!pole.highs); /* failed boot and unfilled window do not arm */
    pole.good=true;for(int i=0;i<MAGNETIC_ENCODER_HIST_LEN;i++)step(&inst);
    assert(pole.trigger.armed && !pole.highs);
    now+=20001;magnetic_encoder_sample_t sample;
    assert(magnetic_encoder_get_sample((void*)&inst,&sample));assert(!sample.velocity_valid && !pole.highs);
    pole.good=false;step(&inst);assert(pole.highs==1); /* first failure, not fail-limit */
    for(int i=0;i<20;i++){step(&inst);}
    assert(pole.highs==1);
    pole.good=true;for(int i=0;i<MAGNETIC_ENCODER_HIST_LEN;i++)step(&inst);
    pole.good=false;step(&inst);assert(pole.highs==1); /* recovery cannot clear */
    source_t cart={.good=true};cart.trigger.raise=raise_pin;cart.trigger.context=&cart;
    magnetic_encoder_inst_t other;assert(magnetic_encoder_sampler_init(&other,&ops,&cart,"cart",clock_now,NULL)==ESP_OK);
    for(int i=0;i<MAGNETIC_ENCODER_HIST_LEN;i++)step(&other);
    cart.good=false;step(&other);assert(cart.highs==0);
    me_failure_trigger_t fresh={.raise=raise_pin,.context=&pole};
    me_failure_trigger_valid(&fresh,false);me_failure_trigger_read_done(&fresh,false);assert(pole.highs==1);
    me_failure_trigger_valid(&fresh,true);me_failure_trigger_read_done(&fresh,true);assert(pole.highs==1);
    me_failure_trigger_read_done(&fresh,false);assert(pole.highs==2);
    puts("pole failure trigger contract passed");
}
