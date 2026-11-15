#include "cartfsm_fixture.h"
static void capture(void)
{
    diag_output_len=0; diag_output[0]=0;
    cmd(CART_CMD_STEPLOSS_QUERY);
    assert(strstr(diag_output,"SL1 1 END 1\n"));
}
int main(void)
{
    disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};
    load_error=ESP_OK; boot();
    cartfsm_step_loss_notice_t notice;
    assert(!cartfsm_take_step_loss_notice(&notice));
    cmd(CART_CMD_CONFIRM_LEFT); cmd(CART_CMD_ENABLE);
    raw=offset; velocity(100);
    command_pos=0; diag_use_snapshot=true;
    diag_snapshot=(cartpos_supervision_t){.position_um=3001,
        .sample={.valid=true,.sample_seq=42,.last_attempt_ok=true}};
    unsigned halts=halt_calls;
    axis_rest=false;
    supervise_once();
    assert(cartfsm_mode()==CM_READY && cartfsm_reason()==CR_NONE && enabled);
    assert(halt_calls==halts && last_velocity==100);
    assert(cartfsm_take_step_loss_notice(&notice));
    assert(notice.event_id==1 && notice.run_id==1 && notice.device_us>0);
    assert(!cartfsm_take_step_loss_notice(&notice));
    velocity(120); assert(last_velocity==120);
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_BUSY"));
    cmd(CART_CMD_STEPTRACE_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_BUSY"));
    axis_rest=true; velocity(0); cmd(CART_CMD_DISABLE);
    capture(); assert(strstr(diag_output," ERROR_UM 3001\n"));
    cmd(CART_CMD_STEPTRACE_QUERY);
    assert(strstr(diag_output,"SLT2 1 BEGIN 1 1\n"));
    assert(strstr(diag_output,"SLT2 1 END 1\n"));
    cmd(CART_CMD_ENABLE); raw=offset; velocity(120);
    diag_snapshot.position_um=99999; supervise_once();
    assert(!cartfsm_take_step_loss_notice(&notice));
    assert(cartfsm_mode()==CM_READY);
    /* 命中观察条件的同一监督拍仍执行软限位。 */
    raw=offset+425000; supervise_once();
    assert(cartfsm_mode()==CM_READY && halt_calls==halts+1);
    power_ready=false; supervise_once();
    assert(cartfsm_mode()==CM_FAULT && cartfsm_reason()==CR_POWER && !enabled);
    power_ready=true; cmd(CART_CMD_RESET); capture();
    raw=offset; cmd(CART_CMD_ENABLE); supervise_once();
    assert(cartfsm_mode()==CM_READY);
    healthy=false; supervise_once();
    assert(cartfsm_mode()==CM_FAULT && cartfsm_reason()==CR_AS5600);
    puts("step-loss observe-only checks passed");
}
