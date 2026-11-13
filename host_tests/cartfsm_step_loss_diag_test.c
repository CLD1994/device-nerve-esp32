/* 复用同一组严格协作者替身，不执行其他测试主函数或真实任务。 */
#define main calibration_fixture_main
#include "cartfsm_calibration_test.c"
#undef main
int main(void) {
    disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};
    load_error=ESP_OK; boot();
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_NONE"));
    cmd(CART_CMD_CONFIRM_LEFT); cmd(CART_CMD_ENABLE);
    assert(s_mode==CM_READY);
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_BUSY"));
    command_pos=10000; raw=999999; /* 旧标量故意不同，必须使用快照中的E。 */
    diag_use_snapshot=true;
    diag_snapshot=(cartpos_supervision_t){.position_um=13000,.velocity_mm_s=812,
        .sample={.valid=true,.velocity_valid=true,.sampled_at_us=1,.sample_seq=42,
            .continuous_gap_us=5000,.continuity_seq=7,.velocity_span_us=16000}};
    assert(!supervise_step_loss(fw_params())); /* 等值不触发。 */
    assert(!s_step_loss_diag.valid && s_mode==CM_READY);
    diag_snapshot.position_um=13001; s_last_cmd_v=1250;
    assert(supervise_step_loss(fw_params()));
    assert(s_mode==CM_FAULT && s_fault_settling && diag_raw_sends==0);
    cartfsm_step_loss_diag_t first=s_step_loss_diag;
    assert(first.valid && first.e_compared_um==13001 && first.c_um==10000);
    assert(first.error_um==3001 && first.threshold_um==3000);
    assert(first.encoder.sample.sample_seq==42 && first.encoder.velocity_mm_s==812);
    assert(first.target_at_accept_mm_s==1250 && first.t_accept_us>=first.t_compare_us);
    diag_snapshot.position_um=999999;
    assert(supervise_step_loss(fw_params())); /* FAULT中不能覆盖首次接受的证据。 */
    assert(s_step_loss_diag.event_id==first.event_id && s_step_loss_diag.e_compared_um==13001);
    cmd(CART_CMD_STEPLOSS_QUERY); assert(!strcmp(reply,"ERR STEPLOSS_BUSY"));
    settle_fault(); assert(!s_fault_settling);
    cmd(CART_CMD_STEPLOSS_QUERY);
    assert(strstr(diag_output," E_COMPARED_UM 13001\n"));
    assert(strstr(diag_output," SAMPLE_SEQ 42\n"));
    assert(strstr(diag_output," END 1\n"));
    enter_power_fault();
    assert(s_reason==CR_POWER && s_step_loss_diag.event_id==first.event_id);
    cmd(CART_CMD_RESET); assert(s_step_loss_diag.event_id==first.event_id);
    enter_fault_record(CR_STEP_LOSS,&first); /* DISABLED不接受旧候选。 */
    assert(s_mode==CM_DISABLED && s_step_loss_diag.event_id==first.event_id);
    cmd(CART_CMD_ENABLE); command_pos=10000; diag_snapshot.position_um=6999;
    assert(supervise_step_loss(fw_params()));
    assert(s_step_loss_diag.error_um==-3001 && s_step_loss_diag.event_id==first.event_id+1);
    settle_fault(); cmd(CART_CMD_RESET); cmd(CART_CMD_ENABLE);
    /* 缺少诊断元数据或无效时钟也不能阻止原位置差故障。 */
    diag_snapshot_available=false; command_pos=0; raw=offset+4000; diag_clock=-100;
    assert(supervise_step_loss(fw_params()));
    assert(s_mode==CM_FAULT && !s_step_loss_diag.metadata_available);
    assert(s_step_loss_diag.e_compared_um==4000);
    settle_fault(); diag_output_len=0;
    cmd(CART_CMD_STEPLOSS_QUERY); assert(strstr(diag_output," TIME_ORDER_OK 0\n"));
    cart_req_t req;
    assert(cartproto_parse_line("STEPLOSS?",&req) && req.cmd==CART_CMD_STEPLOSS_QUERY);
    assert(!cartproto_parse_line("STEPLOSS? extra",&req));
    puts("step-loss diagnostic checks passed");
}
