#include <assert.h>
#include <stdio.h>
#include "cartpower_core.h"
static const cp_timing_t timing = {3000000,10000000,100000,5,500000};
static cp_core_t fresh(void) { cp_core_t s; cp_init(&s, &timing, 0); return s; }
static void verify(cp_core_t *s) {
    for (int i=0;i<5;i++) cp_sample(s,3000000+i*100000,3000000+i*100000,true,true,20000);
    assert(s->state==CP_VERIFIED);
}
int main(void) {
    cp_core_t s=fresh(); assert(!cp_allowed(&s,0));
    cp_sample(&s,100000,100000,true,false,9000); assert(s.state==CP_WAITING);
    verify(&s); assert(cp_allowed(&s,3900000));
    assert(!cp_allowed(&s,3900001)); assert(s.reason==CP_STALE);
    cp_sample(&s,4000000,4000000,true,true,20000); assert(s.state==CP_FAILED);
    s=fresh(); cp_fail(&s,CP_REQUEST); ; /* explicit failure is latched */
    cp_sample(&s,4000000,4000000,true,true,20000); assert(s.reason==CP_REQUEST);
    s=fresh(); cp_sample(&s,10,10,false,true,20000); assert(s.reason==CP_READ);
    s=fresh(); cp_sample(&s,10,10,true,true,21501); assert(s.reason==CP_VOLTAGE);
    s=fresh(); cp_sample(&s,10,10,true,true,-1); assert(s.reason==CP_ADC);
    s=fresh(); cp_sample(&s,10000000,10000000,true,true,20000); assert(s.reason==CP_TIMEOUT);
    s=fresh(); for(int i=0;i<5;i++) cp_sample(&s,3000000,3000000,true,true,20000);
    assert(s.state==CP_WAITING); /* repeated timestamp is not five samples */
    s=fresh(); cp_sample(&s,3000000,3000000,true,true,19000);
    cp_sample(&s,3100000,3100000,true,true,21000);
    cp_sample(&s,3200000,3200000,true,true,18999); assert(s.stable_samples==0);
    s=fresh(); verify(&s); cp_sample(&s,3500000,3500000,true,false,20000); assert(s.reason==CP_PD);
    s=fresh(); verify(&s); cp_sample(&s,3500000,3500000,true,true,21001); assert(s.reason==CP_VOLTAGE);
    s=fresh(); verify(&s); cp_sample(&s,4000001,4000001,true,true,20000); assert(s.reason==CP_STALE);
    s=fresh(); cp_sample(&s,4000000,3000000,true,true,20000); assert(s.reason==CP_STALE);
    s=fresh(); cp_sample(&s,10,11,true,true,20000); assert(s.reason==CP_STALE);
    s=fresh(); for(int i=0;i<4;i++) cp_sample(&s,3000000+i*100000,3000000+i*100000,true,true,20000);
    cp_sample(&s,9000000,9000000,true,true,20000);
    assert(s.state==CP_WAITING && s.stable_samples==1);
    puts("cartpower_core_test: all cases passed");
}
