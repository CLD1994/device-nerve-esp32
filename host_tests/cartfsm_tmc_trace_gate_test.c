#include "cartfsm_fixture.h"
#include "../components/cartfsm/cartfsm_tmc_trace.h"
static unsigned queries, starts;
#ifdef CONFIG_CARTFSM_TMC_TRACE
static unsigned begins, events;
#endif
#ifdef CONFIG_CARTFSM_TMC_TRACE
void cartfsm_tmc_trace_start(void){++starts;}
void cartfsm_tmc_trace_begin_run(uint32_t run,int64_t now){assert(run>0);(void)now;++begins;}
void cartfsm_tmc_trace_event(uint32_t run,uint32_t event,int64_t now){assert(run>0 && event>0);(void)now;++events;}
void cartfsm_tmc_trace_query(void){++queries;}
#endif
int main(void){
 cart_req_t req;
 assert(cartproto_parse_line("TMCTRACE?",&req) && req.cmd==CART_CMD_TMCTRACE_QUERY);
 assert(!cartproto_parse_line("TMCTRACE? extra",&req));
 disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};load_error=ESP_OK;boot();
 cmd(CART_CMD_TMCTRACE_QUERY);
#ifdef CONFIG_CARTFSM_TMC_TRACE
 assert(starts==1 && queries==1);
#else
 assert(starts==0 && queries==0 && !strcmp(reply,"ERR TMCTRACE_DISABLED"));
#endif
 cmd(CART_CMD_CONFIRM_LEFT);cmd(CART_CMD_ENABLE);assert(cartfsm_mode()==CM_READY);
 cmd(CART_CMD_TMCTRACE_QUERY);
#ifdef CONFIG_CARTFSM_TMC_TRACE
 assert(queries==1 && !strcmp(reply,"ERR TMCTRACE_BUSY"));
#else
 assert(!strcmp(reply,"ERR TMCTRACE_DISABLED"));
#endif
 command_pos=100000;axis_rest=false;supervise_once();assert(cartfsm_mode()==CM_FAULT);
 cmd(CART_CMD_TMCTRACE_QUERY);
#ifdef CONFIG_CARTFSM_TMC_TRACE
 assert(queries==1 && !strcmp(reply,"ERR TMCTRACE_BUSY"));
#endif
 axis_rest=true;supervise_once();cmd(CART_CMD_TMCTRACE_QUERY);
#ifdef CONFIG_CARTFSM_TMC_TRACE
 assert(queries==2 && begins==1 && events==1);
#endif
 puts("TMC trace parser/gate: all assertions passed");
}
