#include "cartfsm_fixture.h"
static void stored_track(void) {
    load_error=ESP_OK;
    disk=(cartcal_record_t){.length_um=853437,.pole_zero_urad=456,.pole_inv=1,.mm_per_rev=40};
}
static void missing_record(void) {
    load_error=ESP_FAIL;boot();
    cmd(CART_CMD_ENABLE);assert(!enabled && cartfsm_calib()==CAL_NONE);
    cmd(CART_CMD_CONFIRM_LEFT);assert(!strcmp(reply,"ERR CONFIRM_LEFT"));
}
static void invalid_record(void) {
    stored_track();disk.length_um=0;boot();
    assert(cartfsm_calib()==CAL_NONE);
    cmd(CART_CMD_CONFIRM_LEFT);assert(!referenced && !strcmp(reply,"ERR CONFIRM_LEFT"));
}
static void valid_record(void) {
    stored_track();boot();
    assert(cartfsm_calib()==CAL_PENDING && fw_params()->pole_zero_urad==456 && fw_params()->pole_inv==1);
    cmd(CART_CMD_ENABLE);assert(!enabled);
    healthy=false;cmd(CART_CMD_CONFIRM_LEFT);assert(cartfsm_calib()==CAL_PENDING && !referenced);
    healthy=true;raw=100000;cmd(CART_CMD_CONFIRM_LEFT);
    assert(cartfsm_calib()==CAL_DONE && !enabled && cartpos_position_um()==-426718 && command_pos==-426718);
    raw+=5000;cmd(CART_CMD_ENABLE);assert(enabled && command_pos==cartpos_position_um());
    cmd(CART_CMD_CONFIRM_LEFT);assert(!strcmp(reply,"ERR CONFIRM_LEFT"));
    unsigned writes=vel_writes;
    referenced=false;
    velocity(100);assert(vel_writes==writes); /* 监督拍之前也禁止非零速度。 */
    velocity(0);assert(vel_writes==writes+1 && last_velocity==0);
    assert(cartfsm_mode()==CM_READY && !referenced);
    supervise_once();assert(cartfsm_mode()==CM_FAULT && cartfsm_reason()==CR_AS5600);
    writes=vel_writes;velocity(0);
    assert(cartfsm_mode()==CM_FAULT && vel_writes==writes);
    cmd(CART_CMD_RESET);assert(cartfsm_mode()==CM_DISABLED && cartfsm_calib()==CAL_PENDING && !enabled);
    cmd(CART_CMD_CONFIRM_LEFT);cmd(CART_CMD_ENABLE);
    command_pos+=10000;supervise_once(); /* 指令位置偏差触发真实丢步监督。 */
    assert(cartfsm_mode()==CM_FAULT && cartfsm_reason()==CR_STEP_LOSS);
    cmd(CART_CMD_RESET);assert(cartfsm_mode()==CM_DISABLED && cartfsm_calib()==CAL_DONE && !enabled);
    referenced=false;cmd(CART_CMD_ENABLE);assert(!enabled && cartfsm_calib()==CAL_PENDING);
    scale=41;cmd(CART_CMD_CONFIRM_LEFT);assert(!referenced);cmd(CART_CMD_ENABLE);assert(!enabled);
    scale=40;
    save_error=ESP_FAIL;cmd(CART_CMD_MARK_LEFT);
    assert(cartfsm_calib()!=CAL_LEFT && disk.length_um==853437 && !strcmp(reply,"ERR CAL_STORAGE"));
    save_error=ESP_OK;raw=12345;cmd(CART_CMD_MARK_LEFT);assert(cartfsm_calib()==CAL_LEFT && disk.length_um==0);
    raw+=99999;cmd(CART_CMD_MARK_RIGHT);assert(cartfsm_calib()==CAL_LEFT && disk.length_um==0);
    int64_t old_position=cartpos_position_um();
    raw=12345+900000;old_position+=900000-99999;
    save_error=ESP_FAIL;cmd(CART_CMD_MARK_RIGHT);
    assert(cartfsm_calib()==CAL_LEFT && disk.length_um==0 && cartpos_position_um()==old_position);
    save_error=ESP_OK;during_save_move=150;cmd(CART_CMD_MARK_RIGHT);
    assert(cartfsm_calib()==CAL_DONE && disk.length_um==900000 && cartpos_position_um()==450150 && command_pos==450150);
    during_save_move=0;
    long old=fw_params()->pole_zero_urad;
    save_error=ESP_FAIL;config("POLE_ZERO_URAD",123);assert(fw_params()->pole_zero_urad==old);
    save_error=ESP_OK;config("POLE_ZERO_URAD",123);assert(disk.pole_zero_urad==123 && fw_params()->pole_zero_urad==123);
    config("POLE_INV",2);assert(!strcmp(reply,"ERR POLE_INV"));
    cmd(CART_CMD_MARK_LEFT);raw+=500000;apply_ok=false;cmd(CART_CMD_MARK_RIGHT);
    assert(cartfsm_calib()==CAL_PENDING && disk.length_um==500000 && !strcmp(reply,"ERR CAL_REFERENCE"));
    apply_ok=true;raw=0;cmd(CART_CMD_CONFIRM_LEFT);assert(cartfsm_calib()==CAL_DONE);
    for (int i=0;i<3;i++) {
        raw=10000;cmd(CART_CMD_MARK_LEFT);raw+=500000;
        if(i==0) sample_ref.failure_seq++;
        if(i==1) sample_ref.continuity_seq++;
        if(i==2) sample_ref.scale_revision++;
        referenced=false; /* 采样协作者报告本轮位置参考失效。 */
        cmd(CART_CMD_MARK_RIGHT);
        assert(!strcmp(reply,"ERR CAL_REFERENCE") && disk.length_um==0 && !referenced);
        cmd(CART_CMD_ENABLE);assert(!enabled);
        raw=10000;cmd(CART_CMD_MARK_LEFT);raw+=500000;cmd(CART_CMD_MARK_RIGHT);
        assert(cartfsm_calib()==CAL_DONE && disk.length_um==500000);
    }
    healthy=false;cmd(CART_CMD_MARK_LEFT);
    assert(cartfsm_calib()==CAL_NONE && disk.length_um==0 && !strcmp(reply,"ERR MARK_LEFT"));
    healthy=true;referenced=false;cmd(CART_CMD_CONFIRM_LEFT);assert(!referenced);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"missing")) missing_record();
    else if(!strcmp(argv[1],"invalid")) invalid_record();
    else { assert(!strcmp(argv[1],"valid"));valid_record(); }
    printf("cartfsm calibration (%s): all assertions passed\n",argv[1]);
}
