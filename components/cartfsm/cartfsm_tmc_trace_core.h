/* 有界的软件采证窗口；调用者负责并发串行化，不访问硬件。 */
#pragma once
#include <stdbool.h>
#include <stdint.h>
#define TMC_TRACE_PERIOD_US INT64_C(50000)
#define TMC_TRACE_PRE_US INT64_C(2000000)
#define TMC_TRACE_POST_US INT64_C(5000000)
#define TMC_TRACE_PRE_CAP 80u
#define TMC_TRACE_POST_CAP 204u
#define TMC_TRACE_CAP (TMC_TRACE_PRE_CAP + TMC_TRACE_POST_CAP)
typedef struct {
    uint64_t seq;
    int64_t begin_us, end_us;
    uint32_t status, reg, raw;
} tmc_trace_row_t;
typedef struct {
    uint32_t event_id, run_id;
    int64_t event_us, ended_us;
    unsigned state, count, pre_count; /* 0收集中、1到达时间窗尾、2新运行截断 */
} tmc_trace_header_t;
typedef struct {
    tmc_trace_row_t rows[TMC_TRACE_CAP];
    unsigned head, count;
} tmc_trace_bank_t;
typedef struct {
    uint32_t run;
    uint64_t seq;
    unsigned live, frozen;
    bool valid, latched, needs_trim;
    tmc_trace_bank_t banks[2];
    tmc_trace_header_t header;
} tmc_trace_core_t;
void tmc_trace_core_begin_run(tmc_trace_core_t *,uint32_t,int64_t);
void tmc_trace_core_trigger(tmc_trace_core_t *,uint32_t,uint32_t,int64_t);
void tmc_trace_core_tick(tmc_trace_core_t *,int64_t);
void tmc_trace_core_sample(tmc_trace_core_t *,uint32_t,const tmc_trace_row_t *);
const tmc_trace_header_t *tmc_trace_core_header(tmc_trace_core_t *);
bool tmc_trace_core_row(const tmc_trace_core_t *,unsigned,tmc_trace_row_t *);
