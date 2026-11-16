#include <assert.h>
#include <stdio.h>
#include "../components/cartfsm/cartfsm_tmc_trace_core.h"
static tmc_trace_core_t c;
static void sample(uint32_t run, int64_t begin, int64_t end, unsigned status) {
    tmc_trace_row_t r={.begin_us=begin,.end_us=end,.status=status,.raw=123};
    tmc_trace_core_sample(&c,run,&r);
}
int main(void) {
    tmc_trace_core_begin_run(&c,1,0);
    for(int i=0;i<60;i++) sample(1,i*50000,i*50000+10,0);
    assert(!tmc_trace_core_header(&c));
    tmc_trace_core_trigger(&c,1,7,3000000);
    const tmc_trace_header_t *h=tmc_trace_core_header(&c);
    assert(h && h->event_id==7 && h->pre_count==40 && h->count==40 && h->state==0);
    tmc_trace_row_t r;
    assert(tmc_trace_core_row(&c,0,&r) && r.begin_us==1000000);
    /* Transaction began before event, completed after it: post, not instant. */
    sample(1,2999990,3000010,1);
    assert(h->count==41 && tmc_trace_core_row(&c,40,&r) && r.status==1 && r.raw==0);
    sample(1,3050000,3050010,2);
    assert(tmc_trace_core_row(&c,41,&r) && r.status==2 && r.raw==0);
    tmc_trace_core_trigger(&c,1,8,3100000);assert(h->event_id==7);
    tmc_trace_core_tick(&c,7999999);assert(h->state==0);
    tmc_trace_core_tick(&c,8000000);assert(h->state==1 && h->ended_us==8000000);
    unsigned count=h->count;sample(1,8000001,8000010,0);assert(h->count==count);
    /* New run retains completed evidence, drops old in-flight transaction. */
    tmc_trace_core_begin_run(&c,2,8100000);assert(h->event_id==7 && h->state==1);
    sample(1,8099990,8100010,0);
    tmc_trace_core_trigger(&c,2,9,8200000);
    h=tmc_trace_core_header(&c);assert(h->pre_count==0 && h->count==0);
    tmc_trace_core_begin_run(&c,3,8300000);
    assert(h->state==2 && h->ended_us==8300000);
    /* Real time, not row count, ends a window. */
    tmc_trace_core_trigger(&c,3,10,9000000);
    for(int i=0;i<102;i++) sample(3,9000000+i,9000000+i,0);
    assert(h->count==102 && h->state==0);
    tmc_trace_core_tick(&c,14000000);assert(h->state==1);
    /* Stale prehistory is removed even if the sampler has stalled. */
    tmc_trace_core_begin_run(&c,4,15000000);sample(4,15000000,15000000,0);
    tmc_trace_core_trigger(&c,4,11,18000001);h=tmc_trace_core_header(&c);assert(h->pre_count==0);
    assert(!tmc_trace_core_row(&c,1,&r));
    /* Equality before trigger is a pre row; equality in flight is post. */
    tmc_trace_core_begin_run(&c,5,19000000);
    sample(5,19999990,20000000,0);
    tmc_trace_core_trigger(&c,5,12,20000000);
    h=tmc_trace_core_header(&c);assert(h->pre_count==1);
    sample(5,19999995,20000000,0);
    assert(h->pre_count==1 && h->count==2);
    sample(5,24999990,25000001,0); /* crossed deadline is not in the window */
    assert(h->state==1 && h->count==2 && h->ended_us==25000001);
    /* Full pre window plus boundary-inclusive post records stays bounded. */
    tmc_trace_core_begin_run(&c,6,26000000);
    for(int i=0;i<40;i++)sample(6,26000000+i*50000,26000000+i*50000,0);
    tmc_trace_core_trigger(&c,6,13,28000000);
    for(int i=0;i<=100;i++)sample(6,28000000+i*50000,28000000+i*50000,0);
    h=tmc_trace_core_header(&c);
    assert(h->pre_count==40 && h->count==141 && h->state==1 && h->ended_us==33000000);
    uint64_t seq=0;
    for(unsigned i=0;i<h->count;i++){assert(tmc_trace_core_row(&c,i,&r));assert(r.seq>seq);seq=r.seq;}
    /* A completed transaction waiting to commit at trigger retains pre classification. */
    tmc_trace_core_begin_run(&c,7,34000000);tmc_trace_core_trigger(&c,7,14,35000000);
    sample(7,34999900,34999999,0);h=tmc_trace_core_header(&c);
    assert(h->pre_count==1 && h->count==1);
    sample(6,35000000,35000001,0);assert(h->count==1);
    /* accepted_at can precede the hook: retain rows committed meanwhile. */
    tmc_trace_core_begin_run(&c,8,40000000);
    sample(8,40900000,40900010,0);sample(8,41000001,41000100,0);
    tmc_trace_core_trigger(&c,8,15,41000000);h=tmc_trace_core_header(&c);
    assert(h->pre_count==1 && h->count==2);
    assert(tmc_trace_core_row(&c,1,&r) && r.end_us==41000100);
    tmc_trace_core_begin_run(&c,9,42000000);
    sample(9,43000010,43000020,0);sample(9,43050000,43050010,0);
    tmc_trace_core_trigger(&c,9,16,43000000);h=tmc_trace_core_header(&c);
    assert(h->pre_count==0 && h->count==2);
    /* Far-delayed hook: rows outside the promised post window are excluded. */
    tmc_trace_core_begin_run(&c,10,44000000);
    sample(10,45000001,45000002,0);sample(10,50000001,50000002,0);
    tmc_trace_core_trigger(&c,10,17,45000000);h=tmc_trace_core_header(&c);
    assert(h->count==0); /* rolling 2-second live window already evicted the early row */
    puts("TMC trace core: all assertions passed");
}
