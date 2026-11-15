#include "cartfsm_fixture.h"
int main(void) {
 disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};load_error=ESP_OK;
 boot();cmd(CART_CMD_CONFIRM_LEFT);cmd(CART_CMD_ENABLE);command_pos=0;
 raw=offset+4000;diag_clock=1000;supervise_once();assert(cartfsm_mode()==CM_READY);
 raw=offset+5100;diag_clock+=51000;supervise_once();assert(cartfsm_mode()==CM_READY);
 raw=offset+6200;diag_clock+=51000;supervise_once();
#ifdef CONFIG_CARTFSM_STEP_LOSS_OBSERVE_ONLY
 assert(cartfsm_mode()==CM_READY);
 healthy=false;supervise_once();assert(cartfsm_mode()==CM_FAULT && cartfsm_reason()==CR_AS5600);
#else
 assert(cartfsm_mode()==CM_FAULT && cartfsm_reason()==CR_STEP_LOSS);
#endif
 puts("window verdict/observe-only encoder protection passed");
}
