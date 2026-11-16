/* 有界诊断纯状态：调用者持实例锁；不访问硬件、不格式化日志。 */
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <limits.h>
typedef struct {
    int64_t observed_us, sampled_us, age_us, span_us, gap_us;
    uint64_t seq, failure_seq, continuity_seq;
    uint32_t raw;
    unsigned fill, required, reason;
    uint8_t status;
    bool has_sample, last_attempt_ok, ok, valid;
} me_diag_point_t;
typedef struct { unsigned kind; uint64_t seq; int64_t at_us; uint8_t frame[6]; } me_diag_failure_t;
typedef struct { unsigned kind; int value; me_diag_failure_t failure; } me_diag_log_t;
typedef struct {
    uint32_t run_id;
    uint64_t generation, transitions, dropped;
    bool ready, captured;
    me_diag_point_t previous, before, after;
    me_diag_failure_t failure, first_failure;
    me_diag_log_t logs[8];
    unsigned head, count;
} me_diag_t;
static inline void me_diag_inc(uint64_t *n) { if (*n != UINT64_MAX) ++*n; }
static inline void me_diag_arm(me_diag_t *d, uint32_t run) {
    d->run_id=run; ++d->generation; d->ready=false; d->captured=false;
    d->transitions=0; memset(&d->previous,0,sizeof(d->previous));
}
static inline void me_diag_observe(me_diag_t *d, me_diag_point_t p) {
    if (d->previous.valid && !p.valid) {
        me_diag_inc(&d->transitions);
        if (!d->captured) { d->captured=true; d->before=d->previous; d->after=p; d->first_failure=d->failure; }
    }
    d->previous=p;
}
static inline void me_diag_enqueue(me_diag_t *d, me_diag_log_t p) {
    if(d->count==8) { me_diag_inc(&d->dropped); return; }
    d->logs[(d->head+d->count)%8]=p; ++d->count;
}
static inline bool me_diag_pop(me_diag_t *d, me_diag_log_t *p) {
    if(!d->count) return false;
    *p=d->logs[d->head]; d->head=(d->head+1)%8; --d->count; return true;
}
