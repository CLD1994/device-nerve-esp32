#include "probe_control.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
 const char *bad[]={"RUN 40001 200 ISOLATED","RUN 49999 200 ISOLATED","RUN 50001 200 ISOLATED","RUN 50000 199 ISOLATED","RUN 50000 1001 ISOLATED","RUN 32000 0 ISOLATED","RUN 32000 1001 ISOLATED","RUN 32000 200","RUN -1 200 ISOLATED","RUN 999999999999999999999 200 ISOLATED","RUN 1000 200 ISOLATED extra","ENABLE","VEL 400","RUN 1000", "RUN ",""};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++) assert(probe_parse(bad[i]).kind==CMD_INVALID);
 assert(probe_parse("INFO").kind==CMD_INFO);assert(probe_parse("STOP").kind==CMD_STOP);
 probe_command c=probe_parse("RUN 32000 200 ISOLATED");assert(c.kind==CMD_RUN);
 probe_control p={0};assert(p.state==PROBE_IDLE);
 assert(probe_start(&p,c,1000,true));assert(!probe_start(&p,c,2000,true));
 assert(probe_tick(&p,20999,true)==ACTION_NONE);assert(probe_tick(&p,21000,true)==ACTION_FEED);
 assert(probe_tick(&p,71000,true)==ACTION_STOP);assert(p.state==PROBE_FAULT);
 assert(!probe_start(&p,c,72000,true));probe_stop(&p);assert(p.state==PROBE_FAULT);
 p=(probe_control){0};assert(!probe_start(&p,c,0,false));assert(p.state==PROBE_FAULT);
 p=(probe_control){0};assert(probe_start(&p,c,0,true));assert(probe_tick(&p,100,false)==ACTION_STOP);
 p=(probe_control){0};assert(probe_start(&p,c,1000,true));assert(probe_tick(&p,999,true)==ACTION_STOP);
 p=(probe_control){0};assert(probe_start(&p,c,0,true));
 for(unsigned t=20000;t<200000;t+=20000)assert(probe_tick(&p,t,true)==ACTION_FEED);
 assert(probe_tick(&p,200000,true)==ACTION_STOP);assert(p.state==PROBE_IDLE);
 assert(probe_start(&p,c,300000,true));probe_stop(&p);assert(p.state==PROBE_IDLE);
 probe_command top=probe_parse("RUN 50000 1000 ISOLATED");
 assert(top.kind==CMD_RUN && top.hz==50000 && top.duration_ms==1000);
 assert(probe_parse("RUN 50000 200 ISOLATED").kind==CMD_RUN);
 p=(probe_control){0};assert(probe_start(&p,top,0,true));
 for(unsigned t=20000;t<1000000;t+=20000)assert(probe_tick(&p,t,true)==ACTION_FEED);
 assert(probe_tick(&p,1000000,true)==ACTION_STOP && p.state==PROBE_IDLE);
 top.hz=50001;p=(probe_control){0};assert(!probe_start(&p,top,0,true));
 puts("probe control: PASS (parser, bounds, no auto-start, EN, deadlines, fault latch, explicit rerun)");
}
