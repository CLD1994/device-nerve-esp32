/* STEP_LOSS接受时的固定RAM证据；不是同时采样，也不是物理丢步证明。 */
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "cartpos.h"
typedef struct {
    bool valid;
    bool metadata_available;
    uint32_t event_id, run_at_compare, run_at_accept;
    int64_t t_compare_us, t_accept_us, c_begin_us, c_end_us;
    int64_t e_sensor_um, e_compared_um, c_um, error_um, threshold_um;
    long target_at_accept_mm_s;
    cartpos_supervision_t encoder;
} cartfsm_step_loss_diag_t;
