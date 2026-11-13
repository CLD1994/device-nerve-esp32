#include "probe_control.h"
#include <string.h>
static bool frequency(uint32_t n) {
    const uint32_t values[] = {1000,5000,10000,16000,20000,22000,24000,28000,32000,40000};
    for (unsigned i=0; i<sizeof(values)/sizeof(values[0]); ++i) if(n==values[i]) return true;
    return false;
}
static bool number(const char **s, uint32_t *n) {
    if (**s<'0'||**s>'9') return false;
    *n=0;
    while (**s>='0'&&**s<='9') {
        if (*n>100000) return false;
        *n=*n*10+(unsigned)(*(*s)++-'0');
    }
    return true;
}
probe_command probe_parse(const char *s) {
    probe_command c={CMD_INVALID,0,0};
    if (!strcmp(s,"INFO")) { c.kind=CMD_INFO; return c; }
    if (!strcmp(s,"STOP")) { c.kind=CMD_STOP; return c; }
    if (strncmp(s,"RUN ",4)) return c;
    s+=4;
    if (!number(&s,&c.hz)||*s++!=' '||!number(&s,&c.duration_ms)||strcmp(s," ISOLATED")) return c;
    if (frequency(c.hz)&&c.duration_ms>=200&&c.duration_ms<=1000) c.kind=CMD_RUN;
    return c;
}
void probe_fault(probe_control *p,const char *reason) { p->state=PROBE_FAULT;p->reason=reason; }
void probe_stop(probe_control *p) {
    if(p->state!=PROBE_FAULT) {p->state=PROBE_IDLE;p->reason="STOP";}
}
bool probe_start(probe_control *p,probe_command c,uint64_t now,bool en_high) {
    if(!en_high) {probe_fault(p,"EN_LOW");return false;}
    if(p->state!=PROBE_IDLE || c.kind!=CMD_RUN || !frequency(c.hz) || c.duration_ms<200 || c.duration_ms>1000) return false;
    p->state=PROBE_RUNNING;p->reason="RUN";p->hz=c.hz;
    p->started=p->last_feed=p->last_seen=now;p->deadline=now+(uint64_t)c.duration_ms*1000;
    return true;
}
probe_action probe_tick(probe_control *p,uint64_t now,bool en_high) {
    if(!en_high) {probe_fault(p,"EN_LOW");return ACTION_STOP;}
    if(p->state!=PROBE_RUNNING) return ACTION_NONE;
    if(now<p->last_seen) {probe_fault(p,"CLOCK_BACKWARD");return ACTION_STOP;}
    p->last_seen=now;
    if(now-p->last_feed>=50000) {probe_fault(p,"FEED_LATE");return ACTION_STOP;}
    if(now>=p->deadline) {p->state=PROBE_IDLE;p->reason="DURATION";return ACTION_STOP;}
    if(now-p->last_feed>=20000) {p->last_feed=now;return ACTION_FEED;}
    return ACTION_NONE;
}
