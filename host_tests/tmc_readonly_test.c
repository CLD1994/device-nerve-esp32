#define main calibration_fixture_main
#include "cartfsm_calibration_test.c"
#undef main
#include "../components/tmc2209/tmc2209_response.h"
int main(void) {
 uint8_t b[8]={5,255,0x6c,0,0,0,0,0x81};
 assert(tmc2209_response_matches(b,0x6c,0x81));
 for(unsigned i=0;i<3;i++){b[i]^=1;assert(!tmc2209_response_matches(b,0x6c,0x81));b[i]^=1;}
 assert(!tmc2209_response_matches(b,0x6c,0x80));
 cart_req_t parsed;
 assert(cartproto_parse_line("TMC?",&parsed) && parsed.cmd==CART_CMD_TMC_QUERY);
 assert(!cartproto_parse_line("TMC? 1",&parsed));
 disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};load_error=ESP_OK;boot();
 cmd(CART_CMD_TMC_QUERY);assert(tmc_reads==5 && !enabled && s_mode==CM_DISABLED);
 assert(strstr(diag_output,"TMC1 GCONF 1 0 ") && strstr(diag_output,"TMC1 END\n"));
 tmc_read_ok=false;diag_output[0]=0;diag_output_len=0;cmd(CART_CMD_TMC_QUERY);
 assert(tmc_reads==10 && strstr(diag_output,"TMC1 GCONF 0 "));
 cmd(CART_CMD_CONFIRM_LEFT);cmd(CART_CMD_ENABLE);assert(s_mode==CM_READY);
 cmd(CART_CMD_TMC_QUERY);assert(tmc_reads==10 && !strcmp(reply,"ERR TMC_BUSY"));
 puts("TMC readonly gates/response identity: OK");return 0;
}
