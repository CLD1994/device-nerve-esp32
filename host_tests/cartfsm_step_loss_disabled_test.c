#include "cartfsm_fixture.h"

int main(void) {
    disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};
    load_error=ESP_OK; boot();
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_DISABLED"));
    cmd(CART_CMD_CONFIRM_LEFT); cmd(CART_CMD_ENABLE);
    assert(cartfsm_mode()==CM_READY);
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_DISABLED"));
    command_pos=10000; raw=offset+13000;
    supervise_once(); assert(cartfsm_mode()==CM_READY);
    raw=offset+13001; axis_rest=false;
    unsigned before=halt_calls;
    supervise_once();
    assert(cartfsm_mode()==CM_FAULT && cartfsm_reason()==CR_STEP_LOSS);
    assert(halt_calls==before+1 && last_accel==fw_params()->wdt_dec);
    assert(enabled); /* Ramp stopping retains enable until rest. */
    axis_rest=true; supervise_once(); assert(!enabled);
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_DISABLED"));
    cmd(CART_CMD_RESET); cmd(CART_CMD_ENABLE);
    command_pos=10000; raw=offset+6999;
    supervise_once(); assert(cartfsm_reason()==CR_STEP_LOSS);
    assert(diag_snapshot_reads==0 && diag_clock==0 && diag_raw_sends==0);
    puts("step-loss detection and stop work without diagnostics");
}
