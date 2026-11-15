#include "cartfsm_fixture.h"
extern magnetic_encoder_handle_t test_encoder;
static bool busy, pending, stuck, canceled;
static unsigned starts;
static int64_t begin;
static bool start(magnetic_encoder_handle_t e) {(void)e;starts++;pending=true;begin=diag_clock;return true;}
static void cancel(magnetic_encoder_handle_t e) {(void)e;canceled=true;}
static bool state(magnetic_encoder_handle_t e,magnetic_encoder_read_test_state_t *out)
{
    (void)e;
    *out=(magnetic_encoder_read_test_state_t){.busy=busy||(pending&&(stuck||diag_clock-begin<20000)),.done=true,.count=0};
    return true;
}
static bool row(magnetic_encoder_handle_t e,unsigned i,magnetic_encoder_read_test_row_t *out)
{(void)e;(void)i;(void)out;return false;}
int main(void)
{
    struct magnetic_encoder_s e={.read_test_start=start,.read_test_cancel=cancel,
        .read_test_state=state,.read_test_row=row};
    test_encoder=&e;
    disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};load_error=ESP_OK;boot();
    cart_req_t r;assert(cartproto_parse_line("ENCODERTEST?",&r)&&r.cmd==CART_CMD_ENCODER_TEST);
    assert(!cartproto_parse_line("ENCODERTEST? extra",&r));
    cmd(CART_CMD_ENCODER_TEST);assert(starts==1&&!enabled&&cartfsm_mode()==CM_DISABLED);
    assert(strstr(diag_output,"ERT1 END 0\n"));
    pending=false;cmd(CART_CMD_CONFIRM_LEFT);busy=true;cmd(CART_CMD_ENABLE);
    assert(cartfsm_mode()==CM_DISABLED&&!strcmp(reply,"ERR ENCODERTEST_BUSY"));
    busy=false;cmd(CART_CMD_ENABLE);assert(cartfsm_mode()==CM_READY);
    cmd(CART_CMD_ENCODER_TEST);assert(starts==1&&!strcmp(reply,"ERR ENCODERTEST_BUSY"));
    cmd(CART_CMD_DISABLE);stuck=true;cmd(CART_CMD_ENCODER_TEST);
    assert(canceled&&!strcmp(reply,"ERR ENCODERTEST_TIMEOUT"));
    cmd(CART_CMD_ENABLE);assert(cartfsm_mode()==CM_DISABLED&&!strcmp(reply,"ERR ENCODERTEST_BUSY"));
    puts("encoder read test mode gate checks passed");
}
