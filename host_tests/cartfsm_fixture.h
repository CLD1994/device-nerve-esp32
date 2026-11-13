#pragma once
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "cartfsm.h"
#include "cartcal.h"
#include "cartpos.h"
#include "cartaxis.h"
#include "cartproto.h"
#include "settings.h"
#include "poleang.h"
/* These are test-owned collaborator states, not firmware internals. */
extern cartcal_record_t disk;
extern esp_err_t load_error,save_error;
extern bool healthy,referenced,apply_ok,enabled,power_ready,axis_rest;
extern unsigned vel_writes;
extern long last_velocity,reply_value;
extern int64_t raw,offset,command_pos,during_save_move;
extern float scale;
extern cartpos_reference_t sample_ref;
extern char reply[32];
extern int64_t diag_clock;
extern bool diag_snapshot_available,diag_use_snapshot;
extern cartpos_supervision_t diag_snapshot;
extern char diag_output[8192];
extern size_t diag_output_len;
extern unsigned diag_raw_sends;
void boot(void);
void supervise_once(void);
void cmd(cart_cmd_t c);
void velocity(int32_t v);
void config(const char *name,long value);
