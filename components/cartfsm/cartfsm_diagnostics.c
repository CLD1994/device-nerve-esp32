/* Bounded optional diagnostics. No motor writes, allocation, SPI transactions,
 * UART or formatting in sample/trigger paths. Two banks swap in O(1) on trigger.
 * Protocol formatting happens only through explicit stopped-state queries. */
#include "cartfsm_diagnostics.h"
#include "cartaxis.h"
#include "cartproto.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#ifdef CARTFSM_EVENTS_ENABLED
static portMUX_TYPE lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t current_run, next_event;
static bool latched, pending;
static cartfsm_step_loss_notice_t notice;
#endif
#ifdef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
#define PRE 128u
#define POST 32u
#define CAP (PRE + POST)
#define PERIOD_US 5000
/* Position and command counter are successive reads, not simultaneous. */
typedef struct {
    int64_t observed_us, sample_us, c_begin_us, c_end_us, e_um, c_um;
    uint64_t sequence;
    long target, velocity;
    bool metadata, valid, velocity_valid, last_read_ok;
} row_t;
typedef struct {
    row_t rows[CAP];
    unsigned head, count, post_count;
    int64_t last_us;
} bank_t;
static bank_t banks[2];
static unsigned live, frozen=1;
static bool frozen_valid, post_complete;
static cartfsm_step_loss_diag_t snapshot;
#endif

void cartfsm_diag_begin_run(uint32_t run)
{
#ifdef CARTFSM_EVENTS_ENABLED
    portENTER_CRITICAL(&lock);
    current_run=run; latched=false; pending=false;
#ifdef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
    /* Keep old evidence until the next accepted event. A new run ends any tail. */
    post_complete=true;
    banks[live].head=banks[live].count=banks[live].post_count=0;
    banks[live].last_us=0;
#endif
    portEXIT_CRITICAL(&lock);
#else
    (void)run;
#endif
}

uint32_t cartfsm_diag_trigger(uint32_t run,int64_t now,long target,
                             const cartfsm_step_loss_diag_t *candidate)
{
#ifdef CARTFSM_EVENTS_ENABLED
    uint32_t event=0;
    portENTER_CRITICAL(&lock);
    if (run==current_run && !latched) {
        latched=true;
        event=++next_event;
        notice=(cartfsm_step_loss_notice_t){.event_id=event,.run_id=run,.device_us=now};
        pending=true;
#ifdef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
        if (candidate) {
            snapshot=*candidate;
            snapshot.valid=true; snapshot.event_id=event;
            snapshot.run_at_accept=run; snapshot.t_accept_us=now;
            snapshot.target_at_accept_mm_s=target;
            frozen=live; live^=1u;
            frozen_valid=true; post_complete=false;
            banks[frozen].post_count=0;
        }
#else
        (void)target; (void)candidate;
#endif
    }
    portEXIT_CRITICAL(&lock);
    return event;
#else
    (void)run; (void)now; (void)target; (void)candidate;
    return 0;
#endif
}

bool cartfsm_take_step_loss_notice(cartfsm_step_loss_notice_t *out)
{
#ifdef CARTFSM_EVENTS_ENABLED
    if (!out) return false;
    portENTER_CRITICAL(&lock);
    bool got=pending;
    if (got) { *out=notice; pending=false; }
    portEXIT_CRITICAL(&lock);
    return got;
#else
    (void)out; return false;
#endif
}

void cartfsm_diag_sample(uint32_t run,long target)
{
#ifdef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
    int64_t now=esp_timer_get_time();
    portENTER_CRITICAL(&lock);
    unsigned which=latched?frozen:live;
    bank_t *b=&banks[which];
    bool tail=latched;
    bool collect=run && run==current_run && (!tail || (frozen_valid && !post_complete))
        && (!b->count || now < b->last_us || now-b->last_us>=PERIOD_US);
    portEXIT_CRITICAL(&lock);
    if (!collect) return;
    cartpos_supervision_t e={0};
    bool metadata=cartpos_get_supervision(&e); /* cached snapshot only */
    row_t row={.observed_us=now,.target=target,.metadata=metadata,
        .sample_us=e.sample.sampled_at_us,.sequence=e.sample.sample_seq,
        .e_um=metadata?e.position_um:cartpos_position_um(),
        .velocity=e.velocity_mm_s,.valid=e.sample.valid,
        .velocity_valid=e.sample.velocity_valid,.last_read_ok=e.sample.last_attempt_ok};
    row.c_begin_us=esp_timer_get_time(); row.c_um=cartaxis_cmd_position_um();
    row.c_end_us=esp_timer_get_time();
    portENTER_CRITICAL(&lock);
    /* Discard data if ENABLE/event switched banks while collaborator reads ran. */
    if (run==current_run && tail==latched && which==(latched?frozen:live)) {
        b->rows[b->head]=row; b->head=(b->head+1)%CAP; b->last_us=now;
        if (tail) {
            ++b->count;
            post_complete=++b->post_count>=POST;
        } else if (b->count<PRE) ++b->count;
    }
    portEXIT_CRITICAL(&lock);
#else
    (void)run; (void)target;
#endif
}

void cartfsm_diag_snapshot_query(void)
{
#ifndef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
    cartproto_send_err("STEPLOSS_DISABLED");
#else
    cartfsm_step_loss_diag_t d;
    portENTER_CRITICAL(&lock); d=snapshot; portEXIT_CRITICAL(&lock);
    if (!d.valid) { cartproto_send_err("STEPLOSS_NONE"); return; }
    const magnetic_encoder_sample_t *m=&d.encoder.sample;
    bool ordered=d.c_begin_us>=0 && d.c_end_us>=d.c_begin_us
        && d.t_compare_us>=d.c_end_us && d.t_accept_us>=d.t_compare_us;
    int64_t age=d.metadata_available && m->sampled_at_us>=0
        && d.t_compare_us>=m->sampled_at_us?d.t_compare_us-m->sampled_at_us:-1;
    const struct { const char *name; int64_t value; } fields[]={
        {"VERSION",2},{"TRIGGER",d.trigger},{"HARD_UM",d.hard_um},
        {"GROWTH_UM",d.growth_um},{"WINDOW_US",d.window_elapsed_us},
        {"GROWING_WINDOWS",d.growing_windows},
        {"RUN_COMPARE",d.run_at_compare},{"RUN_ACCEPT",d.run_at_accept},
        {"T_COMPARE_US",d.t_compare_us},{"T_ACCEPT_US",d.t_accept_us},
        {"C_BEGIN_US",d.c_begin_us},{"C_END_US",d.c_end_us},{"TIME_ORDER_OK",ordered},
        {"E_SENSOR_UM",d.e_sensor_um},{"E_COMPARED_UM",d.e_compared_um},
        {"C_UM",d.c_um},{"ERROR_UM",d.error_um},{"THRESHOLD_UM",d.threshold_um},
        {"TARGET_ACCEPT_MM_S",d.target_at_accept_mm_s},{"META_AVAILABLE",d.metadata_available},
        {"ENC_V_MM_S",d.encoder.velocity_mm_s},{"ENC_V_VALID",m->velocity_valid},
        {"ENC_SPAN_US",m->velocity_span_us},{"SAMPLE_US",m->sampled_at_us},{"AGE_US",age},
        {"SAMPLE_SEQ",(int64_t)m->sample_seq},{"FAILURE_SEQ",(int64_t)m->failure_seq},
        {"CONTINUITY_SEQ",(int64_t)m->continuity_seq},{"GAP_US",m->continuous_gap_us},
        {"SAMPLE_VALID",m->valid},{"LAST_READ_OK",m->last_attempt_ok},{"END",1},
    };
    char line[112];
    for (unsigned i=0;i<sizeof(fields)/sizeof(fields[0]);i++) {
        int n=snprintf(line,sizeof(line),"SL1 %" PRIu32 " %s %" PRId64 "\n",
            d.event_id,fields[i].name,fields[i].value);
        if(n>0 && n<(int)sizeof(line)) cartproto_send_raw(line,n);
        else { cartproto_send_err("STEPLOSS_FORMAT"); return; }
    }
#endif
}

void cartfsm_diag_trace_query(void)
{
#ifndef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
    cartproto_send_err("STEPTRACE_DISABLED");
#else
    portENTER_CRITICAL(&lock);
    bool valid=frozen_valid, complete=post_complete;
    uint32_t event=snapshot.event_id,run=snapshot.run_at_accept;
    unsigned count=banks[frozen].count,head=banks[frozen].head,post=banks[frozen].post_count;
    portEXIT_CRITICAL(&lock);
    if (!valid) { cartproto_send_err("STEPTRACE_NONE"); return; }
    if (!complete) { cartproto_send_err("STEPTRACE_BUSY"); return; }
    char line[256];
    int n=snprintf(line,sizeof(line),"SLT4 HEADER %" PRIu32 " %" PRIu32 " %u %u 1\n",event,run,count,post);
    cartproto_send_raw(line,n);
    for(unsigned i=0;i<count;i++) {
        portENTER_CRITICAL(&lock);
        bool same=event==snapshot.event_id && post_complete && cartfsm_mode()!=CM_READY;
        row_t row=banks[frozen].rows[(head+CAP-count+i)%CAP];
        portEXIT_CRITICAL(&lock);
        if (!same) { cartproto_send_err("STEPTRACE_CHANGED"); return; }
        n=snprintf(line,sizeof(line),
            "SLT4 ROW %" PRIu32 " %u %" PRId64 " %" PRId64 " %" PRId64 " %" PRId64
            " %" PRId64 " %" PRId64 " %" PRIu64 " %ld %ld %d %d %d %d\n",
            event,i,row.observed_us,row.sample_us,row.c_begin_us,row.c_end_us,row.e_um,row.c_um,
            row.sequence,row.target,row.velocity,row.metadata,row.valid,row.velocity_valid,row.last_read_ok);
        if(n<=0 || n>=(int)sizeof(line)) {cartproto_send_err("STEPTRACE_FORMAT");return;}
        cartproto_send_raw(line,n);
    }
    n=snprintf(line,sizeof(line),"SLT4 END %" PRIu32 " %u\n",event,count);
    cartproto_send_raw(line,n);
#endif
}
