#include "cartfsm_fixture.h"

int main(void) {
    disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};
    load_error=ESP_OK; boot();
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_DISABLED"));
    cmd(CART_CMD_CONFIRM_LEFT); cmd(CART_CMD_ENABLE);
    assert(cartfsm_mode()==CM_READY);
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_DISABLED"));
    config("ACC_MAX", 7000); assert(last_accel==7000);
    config("WDT_DEC", 5000); assert(strncmp(reply,"ERR",3)==0);
    command_pos=10000; raw=offset+13000;
    supervise_once(); assert(cartfsm_mode()==CM_READY);
    raw=offset+13001; axis_rest=false;
    unsigned before=halt_calls;
    supervise_once();
    assert(cartfsm_mode()==CM_FAULT && cartfsm_reason()==CR_STEP_LOSS);
    assert(halt_calls==before+1 && last_accel==fw_params()->acc_max);
    assert(enabled); /* Ramp stopping retains enable until rest. */
    config("ACC_MAX", 8000); assert(last_accel==7000);
    assert(strncmp(reply,"ERR",3)==0); /* FAULT仍禁止配置，制动档不被更改。 */
    axis_rest=true; supervise_once(); assert(!enabled);
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_DISABLED"));
    cmd(CART_CMD_RESET); cmd(CART_CMD_ENABLE);
    command_pos=10000; raw=offset+6999;
    supervise_once(); assert(cartfsm_reason()==CR_STEP_LOSS);
    assert(diag_snapshot_reads==0 && diag_clock==0 && diag_raw_sends==0);
    puts("step-loss detection and stop work without diagnostics");
}
