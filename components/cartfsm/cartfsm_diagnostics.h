/* Optional evidence plumbing, separate from detection and motor actions. */
#pragma once
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
#include "cartfsm_step_loss_diag.h"
#include "cartfsm.h"
#if defined(CONFIG_CARTFSM_TMC_TRACE) || defined(CONFIG_CARTFSM_STEP_LOSS_EVENTS) || defined(CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS) || defined(CONFIG_CARTFSM_STEP_LOSS_OBSERVE_ONLY)
#define CARTFSM_EVENTS_ENABLED 1
#endif
void cartfsm_diag_begin_run(uint32_t run);
/* Called only after current run/mode acceptance. Returns first event ID, or 0. */
uint32_t cartfsm_diag_trigger(uint32_t run, int64_t now, long target,
                             const cartfsm_step_loss_diag_t *candidate);
void cartfsm_diag_sample(uint32_t run, long target);
void cartfsm_diag_snapshot_query(void);
void cartfsm_diag_trace_query(void);
