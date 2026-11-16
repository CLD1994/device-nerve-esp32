#include "cartfsm_tmc_trace_core.h"
static void pop(tmc_trace_bank_t *b) { b->head=(b->head+1)%TMC_TRACE_CAP; --b->count; }
static void append(tmc_trace_bank_t *b,const tmc_trace_row_t *r) {
    b->rows[(b->head+b->count)%TMC_TRACE_CAP]=*r; ++b->count;
}
/* 裁剪只在采样任务/导出路径执行，事件路径只交换bank。 */
static void trim(tmc_trace_core_t *c) {
    if(!c->needs_trim)return;
    tmc_trace_bank_t *b=&c->banks[c->frozen];
    while(b->count && b->rows[b->head].end_us<c->header.event_us &&
          c->header.event_us-b->rows[b->head].end_us>TMC_TRACE_PRE_US)pop(b);
    while(b->count) {
        int64_t end=b->rows[(b->head+b->count-1)%TMC_TRACE_CAP].end_us;
        if(end<=c->header.event_us || end-c->header.event_us<=TMC_TRACE_POST_US)break;
        --b->count;
    }
    c->header.count=b->count;c->header.pre_count=0;
    while(c->header.pre_count<b->count &&
          b->rows[(b->head+c->header.pre_count)%TMC_TRACE_CAP].end_us<=c->header.event_us)
        ++c->header.pre_count;
    c->needs_trim=false;
}
void tmc_trace_core_tick(tmc_trace_core_t *c,int64_t now) {
    if(c->valid && c->header.state==0 && now>=c->header.event_us &&
       now-c->header.event_us>=TMC_TRACE_POST_US) {
        c->header.state=1; c->header.ended_us=now;
    }
}
void tmc_trace_core_begin_run(tmc_trace_core_t *c,uint32_t run,int64_t now) {
    tmc_trace_core_tick(c,now);
    if(c->valid && c->header.state==0) {c->header.state=2;c->header.ended_us=now;}
    c->run=run;c->latched=false;
    c->banks[c->live].head=c->banks[c->live].count=0;
}
void tmc_trace_core_trigger(tmc_trace_core_t *c,uint32_t run,uint32_t event,int64_t now) {
    if(!event || !run || run!=c->run || c->latched) return;
    c->latched=true;
    tmc_trace_bank_t *b=&c->banks[c->live];
    c->frozen=c->live;c->live^=1u;c->valid=true;c->needs_trim=true;
    c->header=(tmc_trace_header_t){.event_id=event,.run_id=run,.event_us=now,
        .count=b->count,.pre_count=b->count};
    c->banks[c->live].head=c->banks[c->live].count=0;
}
void tmc_trace_core_sample(tmc_trace_core_t *c,uint32_t run,const tmc_trace_row_t *input) {
    if(!run || run!=c->run || input->end_us<input->begin_us || input->status>2) return;
    trim(c);
    tmc_trace_row_t r=*input;r.seq=++c->seq;if(r.status)r.raw=0;
    tmc_trace_bank_t *b=&c->banks[c->live];
    while(b->count && (b->count>=TMC_TRACE_PRE_CAP ||
          r.end_us-b->rows[b->head].end_us>TMC_TRACE_PRE_US)) pop(b);
    append(b,&r);
    /* 单一采样任务的在途读可能在事件后才提交，但时间戳属于前窗。 */
    if(c->valid && c->header.state==0 && run==c->header.run_id &&
       r.end_us<c->header.event_us && c->header.event_us-r.end_us<=TMC_TRACE_PRE_US &&
       c->header.count==c->header.pre_count) {
        tmc_trace_bank_t *f=&c->banks[c->frozen];
        if(c->header.pre_count==TMC_TRACE_PRE_CAP){pop(f);--c->header.count;--c->header.pre_count;}
        append(f,&r);++c->header.count;++c->header.pre_count;
    }
    if(c->valid && c->header.state==0 && run==c->header.run_id &&
       r.end_us>=c->header.event_us && r.end_us-c->header.event_us<=TMC_TRACE_POST_US &&
       c->header.count-c->header.pre_count<TMC_TRACE_POST_CAP) {
        append(&c->banks[c->frozen],&r);++c->header.count;
    }
    tmc_trace_core_tick(c,r.end_us);
}
const tmc_trace_header_t *tmc_trace_core_header(tmc_trace_core_t *c) {
    trim(c);
    return c->valid?&c->header:0;
}
bool tmc_trace_core_row(const tmc_trace_core_t *c,unsigned i,tmc_trace_row_t *out) {
    if(!c->valid || i>=c->header.count)return false;
    const tmc_trace_bank_t *b=&c->banks[c->frozen];
    *out=b->rows[(b->head+i)%TMC_TRACE_CAP];return true;
}
