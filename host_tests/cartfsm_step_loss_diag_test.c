#include "cartfsm_fixture.h"
static void capture(void) {
    diag_output_len=0; diag_output[0]=0;
    cmd(CART_CMD_STEPLOSS_QUERY);
    assert(strstr(diag_output," END 1\n"));
}
int main(void) {
    disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};
    load_error=ESP_OK; boot();
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_NONE"));
    cmd(CART_CMD_CONFIRM_LEFT); cmd(CART_CMD_ENABLE);
    assert(cartfsm_mode()==CM_READY);
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_BUSY"));
    command_pos=10000; raw=999999; /* Scalar deliberately differs from snapshot E. */
    diag_use_snapshot=true;
    diag_snapshot=(cartpos_supervision_t){.position_um=13000,.velocity_mm_s=812,
        .sample={.valid=true,.velocity_valid=true,.sampled_at_us=1,.sample_seq=42,
            .continuous_gap_us=5000,.continuity_seq=7,.velocity_span_us=16000}};
    supervise_once(); assert(cartfsm_mode()==CM_READY); /* Equality does not fault. */
    raw=offset+13000; velocity(100); raw=999999; diag_snapshot.position_um=13001; axis_rest=false;
    supervise_once(); assert(cartfsm_mode()==CM_FAULT && cartfsm_reason()==CR_STEP_LOSS);
    assert(diag_raw_sends==0);
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_BUSY"));
    diag_snapshot.position_um=999999; supervise_once();
    assert(diag_raw_sends==0); /* No formatting/output in supervision. */
    axis_rest=true; supervise_once(); capture();
    assert(strstr(diag_output,"SL1 1 E_COMPARED_UM 13001\n"));
    assert(strstr(diag_output," C_UM 10000\n"));
    assert(strstr(diag_output," ERROR_UM 3001\n"));
    assert(strstr(diag_output," THRESHOLD_UM 3000\n"));
    assert(strstr(diag_output," SAMPLE_SEQ 42\n"));
    assert(strstr(diag_output," ENC_V_MM_S 812\n"));
    assert(strstr(diag_output," TARGET_ACCEPT_MM_S 100\n"));
    power_ready=false; supervise_once(); assert(cartfsm_reason()==CR_POWER);
    power_ready=true; cmd(CART_CMD_RESET); assert(cartfsm_mode()==CM_DISABLED);
    capture(); assert(strstr(diag_output,"SL1 1 E_COMPARED_UM 13001\n"));
    supervise_once(); capture(); /* DISABLED cannot replace evidence. */
    assert(strstr(diag_output,"SL1 1 E_COMPARED_UM 13001\n"));
    cmd(CART_CMD_ENABLE); command_pos=10000; diag_snapshot.position_um=6999;
    supervise_once(); supervise_once(); capture();
    assert(strstr(diag_output,"SL1 2 ERROR_UM -3001\n"));
    cmd(CART_CMD_RESET); cmd(CART_CMD_ENABLE);
    diag_snapshot_available=false; command_pos=0; raw=offset+4000; diag_clock=-100;
    supervise_once(); assert(cartfsm_mode()==CM_FAULT);
    supervise_once(); capture();
    assert(strstr(diag_output,"SL1 3 E_COMPARED_UM 4000\n"));
    assert(strstr(diag_output," META_AVAILABLE 0\n"));
    assert(strstr(diag_output," TIME_ORDER_OK 0\n"));
    cart_req_t req;
    assert(cartproto_parse_line("STEPLOSS?",&req) && req.cmd==CART_CMD_STEPLOSS_QUERY);
    assert(!cartproto_parse_line("STEPLOSS? extra",&req));
    puts("step-loss diagnostic public-interface checks passed");
}
