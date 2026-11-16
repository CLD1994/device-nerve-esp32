#include "cartfsm_fixture.h"
static me_diag_t evidence;
static unsigned arms;
void poleang_diagnostic_arm(uint32_t run){arms++;me_diag_arm(&evidence,run);}
bool poleang_diagnostic_get(me_diag_t *out){*out=evidence;return true;}
int main(void){
 disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};load_error=ESP_OK;boot();
 cart_req_t req;assert(cartproto_parse_line("POLEDIAG?",&req)&&req.cmd==CART_CMD_POLEDIAG_QUERY);
 assert(!cartproto_parse_line("POLEDIAG? extra",&req));
 cmd(CART_CMD_POLEDIAG_QUERY);assert(strstr(diag_output,"POLED1 BEGIN 0 0 0 0\nPOLED1 END 0\n"));
 cmd(CART_CMD_ENABLE);assert(arms==0); /* no reference */
 cmd(CART_CMD_CONFIRM_LEFT);cmd(CART_CMD_ENABLE);assert(arms==1 && evidence.run_id==1);
 cmd(CART_CMD_POLEDIAG_QUERY);assert(!strcmp(reply,"ERR POLEDIAG_BUSY"));
 cmd(CART_CMD_DISABLE); assert(cartfsm_mode()==CM_DISABLED);
 evidence.captured=true;evidence.transitions=1;
 evidence.before=(me_diag_point_t){.observed_us=20000,.sampled_us=20000,.age_us=0,
  .span_us=16000,.gap_us=20000,.seq=41,.failure_seq=6,.fill=17,.required=17,
  .has_sample=true,.last_attempt_ok=true,.ok=true,.valid=true,.raw=12345};
 evidence.after=evidence.before;evidence.after.observed_us=21000;evidence.after.age_us=1000;
 evidence.after.last_attempt_ok=false;evidence.after.valid=false;evidence.after.reason=2|8;
 evidence.after.failure_seq=7;evidence.after.fill=0;evidence.after.span_us=0;
 evidence.first_failure=(me_diag_failure_t){.kind=3,.seq=7,.at_us=21000,.frame={1,2,3,4,5,6}};
 diag_output_len=0;diag_output[0]=0;cmd(CART_CMD_POLEDIAG_QUERY);
 assert(strstr(diag_output,"POLED1 FAIL 3 7 21000 1 2 3 4 5 6\n"));assert(evidence.captured);
 fputs(diag_output,stdout);
 cmd(CART_CMD_ENABLE);assert(arms==2 && evidence.run_id==2 && !evidence.captured);
 cmd(CART_CMD_DISABLE);
 evidence.run_id=UINT32_MAX;evidence.captured=true;evidence.after.raw=2097151;
 diag_output_len=0;diag_output[0]=0;cmd(CART_CMD_POLEDIAG_QUERY);
 assert(strstr(diag_output,"POLED1 BEGIN 4294967295 1 "));
 assert(strstr(diag_output,"POLED1 END 4294967295\n"));
 assert(strstr(diag_output," 2097151 0\n"));
 puts("pole diagnostic query/rearm passed");
}
