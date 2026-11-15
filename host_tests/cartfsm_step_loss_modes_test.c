#include "cartfsm_fixture.h"
#include <inttypes.h>
int main(void) {
    disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};
    load_error=ESP_OK; boot(); cmd(CART_CMD_CONFIRM_LEFT); cmd(CART_CMD_ENABLE);
    cmd(CART_CMD_RUN_QUERY); assert(!strcmp(reply,"OK RUN") && reply_value==1);
    raw=offset; command_pos=0; velocity(100);
    /* Fill pre-event samples. */
    for (int i=0;i<140;i++) { raw=offset+i*10; diag_clock+=5000; supervise_once(); }
    raw=offset+4000;
    unsigned before=halt_calls;
    diag_clock+=5000; supervise_once();
#ifdef CONFIG_CARTFSM_STEP_LOSS_OBSERVE_ONLY
    assert(cartfsm_mode()==CM_READY && enabled);
    assert(halt_calls==before && last_velocity==100);
#else
    (void)before;
    assert(cartfsm_mode()==CM_FAULT);
#endif
    cartfsm_step_loss_notice_t n;
    assert(cartfsm_take_step_loss_notice(&n));
    assert(n.event_id==1 && n.run_id==1 && n.device_us>0);
    assert(!cartfsm_take_step_loss_notice(&n));
    for (int i=0;i<40;i++) { diag_clock+=5000; supervise_once(); }
    assert(!cartfsm_take_step_loss_notice(&n));
#ifdef CONFIG_CARTFSM_STEP_LOSS_OBSERVE_ONLY
    velocity(0); cmd(CART_CMD_DISABLE);
#endif
#ifdef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
    diag_output_len=0; diag_output[0]=0;
    cmd(CART_CMD_STEPTRACE_QUERY);
    assert(strstr(diag_output,"SLT4 HEADER 1 1 160 32 1\n"));
    assert(strstr(diag_output,"SLT4 END 1 160\n"));
    const char *at=diag_output;
    int64_t previous=-1;
    for (unsigned i=0;i<160;i++) {
        at=strstr(at,"SLT4 ROW "); assert(at);
        unsigned event,index; int64_t t,sample,cb,ce,e,c;
        assert(sscanf(at,"SLT4 ROW %u %u %" SCNd64 " %" SCNd64 " %" SCNd64 " %" SCNd64 " %" SCNd64 " %" SCNd64,
            &event,&index,&t,&sample,&cb,&ce,&e,&c)==8);
        assert(event==1 && index==i && t>previous); previous=t;
        if(i<127) assert(e==(int64_t)(i+13)*10);
        else assert(e==4000); /* trigger-adjacent row + exactly32 tail rows */
        at++;
    }
#else
    assert(diag_snapshot_reads==0);
    cmd(CART_CMD_STEPTRACE_QUERY); assert(!strcmp(reply,"ERR STEPTRACE_DISABLED"));
#endif
    cmd(CART_CMD_RESET); cmd(CART_CMD_ENABLE); command_pos=0; raw=offset+4000;
    diag_clock+=5000; supervise_once();
    assert(cartfsm_take_step_loss_notice(&n) && n.event_id==2 && n.run_id==2);
#ifdef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
    /* Starting a new run truncates an old tail but keeps its actual evidence. */
#ifdef CONFIG_CARTFSM_STEP_LOSS_OBSERVE_ONLY
    velocity(0); cmd(CART_CMD_DISABLE);
#else
    diag_clock+=5000; supervise_once(); cmd(CART_CMD_RESET);
#endif
    cmd(CART_CMD_ENABLE); velocity(0); cmd(CART_CMD_DISABLE);
    diag_output_len=0; diag_output[0]=0; cmd(CART_CMD_STEPTRACE_QUERY);
    assert(strstr(diag_output,"SLT4 HEADER 2 2 "));
    assert(strstr(diag_output,"SLT4 END 2 "));
#endif
    puts("step-loss event/rearm/trace mode checks passed");
}
