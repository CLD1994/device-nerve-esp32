/*
 * cartfsm — 模式机实现：监督任务与命令执行
 *
 * 并发布局：exec 回调运行在 comm_task（CPU0）；监督任务运行在
 * CPU1。共享状态用 s_lock 自旋锁保护写入；模式枚举读取原子。
 * cartaxis / cartproto 发送均为线程安全接口。
 *
 * FAULT 停机次序（契约）：目标斜坡置 0（电机加速度临时切到
 * WDT_DEC 档）→ 监督任务等速度精确为零 → EN 关 → 推 MODE 行。
 * RESET 离开 FAULT 时恢复 ACC_MAX 档并清电机状态。
 * POWER故障例外：立即停止STEP并禁用，不能依赖缺电时斜坡制动。
 */

#include "cartfsm.h"

#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <inttypes.h>
#include "esp_timer.h"
#include "tmc2209.h"
#include "cartfsm_step_loss_diag.h"

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_task_wdt.h"

#include "cartpos.h"
#include "poleang.h"
#include "cartaxis.h"
#include "cartproto.h"
#include "cartcal.h"
#include "settings.h"
#include "cartpower.h"

static const char *TAG = "cartfsm";

#define FSM_TASK_PRIO     4
#define FSM_TASK_CORE     1
#define FSM_TASK_STACK    4096
#define FSM_PERIOD_MS     1

/* ---- 共享状态 ---- */
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static volatile cm_mode_t   s_mode = CM_DISABLED;
static volatile cm_reason_t s_reason = CR_NONE;
static volatile long s_last_cmd_v = 0;     /* 最近有效目标（软限位持续钳制） */
static volatile bool s_fault_settling = false;  /* FAULT 斜坡停机进行中 */
static bool s_started = false;
/* 与模式转换/读出同受s_output_lock保护，RESET不清除证据。 */
static cartfsm_step_loss_diag_t s_step_loss_diag;
static uint32_t s_step_loss_event;
static uint32_t s_run_id;
/* 串行化使能/VEL与供电急停；锁内不做I2C或NVS。 */
static SemaphoreHandle_t s_output_lock;

/* ---- 本次定位状态与已提交的装置标定 ---- */
static calib_state_t s_calib = CAL_NONE;
static int64_t s_e_left_um = 0;   /* 左标 E（µm） */
static long s_calib_l_um = 0;  /* 标定行程 L（CAL_DONE 后有效） */

static cartcal_record_t s_saved;
static cartpos_reference_t s_left_ref;
static esp_err_t s_storage_status = ESP_OK;

static bool saved_track_valid(void)
{
    return cm_calib_valid(s_saved.length_um) &&
           s_saved.mm_per_rev == settings_units_per_rev();
}

/* 仅 comm_task 修改标定状态；监督任务只停机，不能与标定命令竞争写状态。 */
static void check_reference(void)
{
    if (s_calib == CAL_DONE &&
        (!saved_track_valid() || !cartpos_reference_is_valid())) {
        s_calib = saved_track_valid() ? CAL_PENDING : CAL_NONE;
    }
}

static bool save_record(const cartcal_record_t *record)
{
    s_storage_status = cartcal_save(record);
    if (s_storage_status != ESP_OK) {
        ESP_LOGE(TAG, "标定保存失败: %d", (int)s_storage_status);
        return false;
    }
    s_saved = *record;
    return true;
}

/* 流程测试注入钩子（CONFIG_CARTFSM_TEST_HOOKS）：0 无、1 AS5600、2 MT6835 */
#ifdef CONFIG_CARTFSM_TEST_HOOKS
static volatile int s_test_enc_fail = 0;
static volatile long s_test_loss_bias_um = 0;   /* 丢步判定的 E 偏置注入 */
#endif

/* ---- 模式/原因字符串 ---- */
static const char *mode_str(cm_mode_t m)
{
    switch (m) {
    case CM_DISABLED: return "DISABLED";
    case CM_READY:    return "READY";
    case CM_FAULT:    return "FAULT";
    default:          return "DISABLED";
    }
}

static const char *reason_str(cm_reason_t r)
{
    switch (r) {
    case CR_NONE:      return "NONE";
    case CR_STEP_LOSS: return "STEP_LOSS";
    case CR_AS5600:    return "AS5600";
    case CR_MT6835:    return "MT6835";
    case CR_POWER:     return "POWER";
    default:           return "NONE";
    }
}

/* ---- 参数作用点 ---- */

/* 软限位窗口：[-L/2+m, +L/2-m] */
static void soft_window(const fw_params_t *p, long *min_um, long *max_um)
{
    *min_um = -s_calib_l_um / 2 + p->x_margin_um;
    *max_um = s_calib_l_um / 2 - p->x_margin_um;
}

static void params_apply_engine(void)
{
    const fw_params_t *p = fw_params();
    cartaxis_set_accel_mm_s2(p->acc_max);
    cartaxis_set_decel_mm_s2(p->wdt_dec);
    cartaxis_set_wdt_ms(p->wdt_ms);
}

/* 软限位钳制收口：读当前位置、按窗口钳制 v、持锁提交 s_last_cmd_v、
 * 锁外下发电机。exec_vel 与 VEL_MAX 运行中收紧共用。
 * 电机调用在 s_lock 之外（不与电机实现内部的锁嵌套）。 */
static void clamp_and_commit_velocity(long v_mm_s)
{
    xSemaphoreTake(s_output_lock, portMAX_DELAY);
    if (s_mode != CM_READY || !cartpower_ready()
        || (v_mm_s != 0 && (!cartpos_reference_is_valid() || !saved_track_valid()))) {
        xSemaphoreGive(s_output_lock);
        return;
    }
    const fw_params_t *p = fw_params();
    long xmin, xmax;
    soft_window(p, &xmin, &xmax);
    long eff = cm_soft_limit_clamp((long)cartpos_position_um(),
                                   xmin, xmax, v_mm_s);

    portENTER_CRITICAL(&s_lock);
    s_last_cmd_v = eff;
    portEXIT_CRITICAL(&s_lock);

    cartaxis_set_vel_mm_s(eff);
    xSemaphoreGive(s_output_lock);
}

/* 监督拍软限位持续钳制：当前目标被窗口钳为不同值时斜坡停并清
 * 目标。读/写 s_last_cmd_v 持锁，电机调用在锁外。 */
static void supervise_soft_limit(const fw_params_t *p)
{
    xSemaphoreTake(s_output_lock, portMAX_DELAY);
    if (s_mode != CM_READY) {
        xSemaphoreGive(s_output_lock);
        return;
    }
    portENTER_CRITICAL(&s_lock);
    long cmd = s_last_cmd_v;
    portEXIT_CRITICAL(&s_lock);

    long xmin, xmax;
    soft_window(p, &xmin, &xmax);
    long eff = cm_soft_limit_clamp((long)cartpos_position_um(),
                                   xmin, xmax, cmd);
    if (eff != cmd) {
        /* 条件清零：仅当判定所依据的目标未被新命令覆盖时才停并
         * 清零。若在判定与清零之间 exec_vel 已提交新目标，清零会
         * 使 s_last_cmd_v 与电机实际目标脱钩（记录 0 而电机仍在
         * 运动），软限位对该目标持续失效。被覆盖则本拍不动作，
         * 下一拍以新目标为基准重新钳制。 */
        portENTER_CRITICAL(&s_lock);
        bool still_old = (s_last_cmd_v == cmd);
        if (still_old) {
            s_last_cmd_v = 0;
        }
        portEXIT_CRITICAL(&s_lock);
        if (still_old) {
            cartaxis_halt();
        }
    }
    xSemaphoreGive(s_output_lock);
}

static void params_apply_one(const char *name)
{
    const fw_params_t *p = fw_params();
    switch (fw_params_find(name)) {
    case FP_ACC_MAX:
        cartaxis_set_accel_mm_s2(p->acc_max);
        break;
    case FP_WDT_DEC:
        cartaxis_set_decel_mm_s2(p->wdt_dec);
        break;
    case FP_WDT_MS:
        cartaxis_set_wdt_ms(p->wdt_ms);
        break;
    case FP_VEL_MAX:
        /* 运行中收紧 VEL_MAX 立即约束当前运动（protocol.md 收紧语义） */
        portENTER_CRITICAL(&s_lock);
        long cur = s_last_cmd_v;
        portEXIT_CRITICAL(&s_lock);
        if (cur > p->vel_max || cur < -p->vel_max) {
            long v = (cur > 0) ? p->vel_max : -p->vel_max;
            clamp_and_commit_velocity(v);
        }
        break;
    default:
        break;   /* 其余参数（X_MARGIN_UM/标定量）为读取点即时生效 */
    }
}

/* ---- 模式转换辅助 ---- */

static void push_mode(cm_mode_t m, cm_reason_t r)
{
    cartproto_send_mode(mode_str(m), reason_str(r));
}

/* 调用者持输出锁。缺电时不能依赖斜坡制动，因此立即停STEP并禁用。 */
static void power_stop_locked(void)
{
    portENTER_CRITICAL(&s_lock);
    s_mode = CM_FAULT;
    s_reason = CR_POWER;
    s_last_cmd_v = 0;
    s_fault_settling = false;
    portEXIT_CRITICAL(&s_lock);
    cartaxis_stop();
    cartaxis_enable(false);
}

static void enter_power_fault(void)
{
    xSemaphoreTake(s_output_lock, portMAX_DELAY);
    if (s_mode == CM_DISABLED) {
        xSemaphoreGive(s_output_lock);
        return; /* RESET已生效；供电门仍锁定，不能靠旧监督快照重入FAULT。 */
    }
    bool changed = s_mode != CM_FAULT || s_reason != CR_POWER;
    power_stop_locked();
    xSemaphoreGive(s_output_lock);
    if (changed) push_mode(CM_FAULT, CR_POWER);
}

static void enter_fault_record(cm_reason_t r, const cartfsm_step_loss_diag_t *candidate)
{
    xSemaphoreTake(s_output_lock, portMAX_DELAY);
    if (s_mode != CM_READY) {
        xSemaphoreGive(s_output_lock);
        return;
    }
    int64_t accepted_at = candidate ? esp_timer_get_time() : 0;
    long target_before_stop = s_last_cmd_v;
    portENTER_CRITICAL(&s_lock);
    s_mode = CM_FAULT;
    s_reason = r;
    s_fault_settling = true;
    portEXIT_CRITICAL(&s_lock);

    /* 次序 ①：目标斜坡置 0，以 WDT_DEC 档减速 */
    const fw_params_t *p = fw_params();
    cartaxis_set_accel_mm_s2(p->wdt_dec);
    cartaxis_halt();
    /* 安全停车先提交。固定大小复制，无格式化/串口/NVS或动态分配。 */
    if (r == CR_STEP_LOSS && candidate) {
        s_step_loss_diag = *candidate;
        s_step_loss_diag.valid = true;
        s_step_loss_diag.event_id = ++s_step_loss_event;
        s_step_loss_diag.run_at_accept = s_run_id;
        s_step_loss_diag.t_accept_us = accepted_at;
        s_step_loss_diag.target_at_accept_mm_s = target_before_stop;
    }
    xSemaphoreGive(s_output_lock);
    /* ②③（等 vel_now==0 → EN 关 → 推 MODE）由监督任务完成 */
}

static void enter_fault(cm_reason_t r)
{
    enter_fault_record(r, NULL);
}

/* ---- 命令处理（cartproto exec 回调，CPU0） ----
 * exec_cmd 只做分派；各命令的业务细节在 exec_* 函数。 */

#ifdef CONFIG_CARTFSM_TEST_HOOKS
/* 流程测试注入：读数偏置一次性消费（MARK 标记与丢步判定拍共用） */
static long consume_test_bias(long e_um)
{
    e_um += s_test_loss_bias_um;
    s_test_loss_bias_um = 0;
    return e_um;
}
#endif

static void exec_query(void)
{
    cm_mode_t m;
    cm_reason_t r;
    portENTER_CRITICAL(&s_lock);
    m = s_mode;
    r = s_reason;
    portEXIT_CRITICAL(&s_lock);
    push_mode(m, r);
}

static void exec_mark_left(void)
{
    cartpos_reference_t ref;
    if (s_mode != CM_DISABLED) {
        cartproto_send_err("MARK_LEFT");
        return;
    }
    /* 先提交失效记录：ACK 后即使掉电也不能复用上一段行程。 */
    cartcal_record_t record = s_saved;
    record.length_um = 0;
    record.mm_per_rev = settings_units_per_rev();
    if (!save_record(&record)) {
        s_calib = saved_track_valid() ? CAL_PENDING : CAL_NONE;
        cartproto_send_err("CAL_STORAGE");
        return;
    }
    s_calib = CAL_NONE;
    s_calib_l_um = 0;
    /* Flash提交可能暂停采样；在它完成之后观察稳定窗口，不能把该暂停
     * 误当成左右标记之间的位移丢失。保存失效但读数失败时需重试LEFT。 */
    if (!cartpos_capture_reference(&ref)) {
        cartproto_send_err("MARK_LEFT");
        return;
    }
    s_left_ref = ref;
    s_e_left_um = ref.raw_um;
#ifdef CONFIG_CARTFSM_TEST_HOOKS
    s_e_left_um = consume_test_bias((long)s_e_left_um);
#endif
    s_calib_l_um = 0;
    s_calib = CAL_LEFT;
    cartproto_send_ok("MARK_LEFT", (long)cartpos_position_um());
}

static void exec_mark_right(void)
{
    cartpos_reference_t ref;
    if (s_mode != CM_DISABLED || s_calib != CAL_LEFT ||
        s_saved.mm_per_rev != settings_units_per_rev() ||
        !cartpos_capture_reference(&ref)) {
        cartproto_send_err("MARK_RIGHT");
        return;
    }
    if (ref.scale_revision != s_left_ref.scale_revision ||
        ref.failure_seq != s_left_ref.failure_seq ||
        ref.continuity_seq != s_left_ref.continuity_seq) {
        cartproto_send_err("CAL_REFERENCE"); /* 左右点之间丢失连续位置，必须重标 LEFT */
        return;
    }
    int64_t right = ref.raw_um;
#ifdef CONFIG_CARTFSM_TEST_HOOKS
    right = consume_test_bias((long)right);
#endif
    uint64_t length = (uint64_t)right - (uint64_t)s_e_left_um;
    if (right < s_e_left_um || length > INT32_MAX || !cm_calib_valid((long)length)) {
        cartproto_send_err("MARK_RIGHT");
        return;
    }
    cartcal_record_t record = s_saved;
    record.length_um = (int32_t)length;
    if (!save_record(&record)) {
        cartproto_send_err("CAL_STORAGE"); /* 留在 LEFT，允许同位置重试 */
        return;
    }
    s_calib_l_um = record.length_um;
    s_calib = CAL_PENDING;
    /* 按写入前的右端快照定基，NVS耗时内真实位移不能被吞掉。 */
    if (!cartpos_apply_reference(&ref, length / 2)) {
        cartproto_send_err("CAL_REFERENCE"); /* 已保存，但必须重新确认左端 */
        return;
    }
    cartaxis_set_position_um((long)cartpos_position_um());
    s_calib = CAL_DONE;
    cartproto_send_ok("MARK_RIGHT", record.length_um);
}

static void exec_confirm_left(void)
{
    cartpos_reference_t ref;
    if (s_mode != CM_DISABLED || s_calib == CAL_LEFT || !saved_track_valid() ||
        !cartpos_capture_reference(&ref) ||
        !cartpos_apply_reference(&ref, -(int64_t)s_saved.length_um / 2)) {
        cartproto_send_err("CONFIRM_LEFT");
        return;
    }
    s_calib_l_um = s_saved.length_um;
    cartaxis_set_position_um((long)cartpos_position_um());
    s_calib = CAL_DONE;
    cartproto_send_ok("CONFIRM_LEFT", -s_calib_l_um / 2);
}

static void exec_calib_query(void)
{
    check_reference();
    cartproto_send_ok("CAL_STATE", s_calib);
    cartproto_send_ok("CAL_LENGTH_UM", saved_track_valid() ? s_saved.length_um : 0);
    cartproto_send_ok("CAL_SAVED", saved_track_valid());
    cartproto_send_ok("CAL_STORAGE", s_storage_status);
}

static void exec_enable(void)
{
    xSemaphoreTake(s_output_lock, portMAX_DELAY);
    if (s_mode != CM_DISABLED) {
        xSemaphoreGive(s_output_lock);
        return;
    }
    if (!cartpower_ready()) {
        xSemaphoreGive(s_output_lock);
        cartproto_send_err("POWER");
        return;
    }
    check_reference();
    if (s_calib != CAL_DONE) {
        xSemaphoreGive(s_output_lock);
        cartproto_send_err("ENABLE");
        return;
    }
    cartaxis_set_position_um((long)cartpos_position_um());
    if (!cartpos_reference_is_valid() || !saved_track_valid()) {
        check_reference();
        xSemaphoreGive(s_output_lock);
        cartproto_send_err("ENABLE");
        return;
    }
    cartaxis_enable(true);
    /* 覆盖检查与开启间缓存失效的窗口；下个监督拍仍持续检查。 */
    if (!cartpower_ready()) {
        power_stop_locked();
        xSemaphoreGive(s_output_lock);
        push_mode(CM_FAULT, CR_POWER);
        return;
    }
    portENTER_CRITICAL(&s_lock);
    s_mode = CM_READY;
    ++s_run_id;
    s_reason = CR_NONE;
    s_last_cmd_v = 0;
    portEXIT_CRITICAL(&s_lock);
    xSemaphoreGive(s_output_lock);
    push_mode(CM_READY, CR_NONE);
}

/* 仅正常零速禁用；与VEL、ENABLE及故障输出共用互斥量。 */
static void exec_disable(void)
{
    xSemaphoreTake(s_output_lock, portMAX_DELAY);
    if (s_mode == CM_READY) {
        /* 精确速度检查与清目标必须由引擎在同一锁内完成。 */
        if (!cartaxis_try_stop_at_rest()) {
            xSemaphoreGive(s_output_lock);
            cartproto_send_err("BUSY");
            return;
        }
        cartaxis_enable(false);
        portENTER_CRITICAL(&s_lock);
        s_last_cmd_v = 0;
        s_fault_settling = false;
        s_mode = CM_DISABLED;
        s_reason = CR_NONE;
        portEXIT_CRITICAL(&s_lock);
    }
    cm_mode_t mode = s_mode;
    cm_reason_t reason = s_reason;
    xSemaphoreGive(s_output_lock);
    push_mode(mode, reason);
}

static void exec_reset(void)
{
    xSemaphoreTake(s_output_lock, portMAX_DELAY);
    cm_mode_t m = s_mode;
    cm_reason_t r = s_reason;
    if (!cm_step(&m, &r, CE_CMD_RESET)) {
        xSemaphoreGive(s_output_lock);
        return;   /* 仅 FAULT 生效 */
    }
    portENTER_CRITICAL(&s_lock);
    s_mode = CM_DISABLED;
    s_reason = CR_NONE;
    s_fault_settling = false;
    s_last_cmd_v = 0;
    portEXIT_CRITICAL(&s_lock);

    cartaxis_stop();               /* 斜坡未完也立即急停 */
    cartaxis_enable(false);
    check_reference();
    params_apply_engine();       /* 恢复 ACC_MAX 档等 */
    xSemaphoreGive(s_output_lock);
    push_mode(CM_DISABLED, CR_NONE);
}

static void exec_vel(int32_t v_mm_s)
{
    portENTER_CRITICAL(&s_lock);
    cm_mode_t cur = s_mode;
    portEXIT_CRITICAL(&s_lock);
    if (cur != CM_READY) {
        return;   /* 仅 READY 执行；持锁复查防 FAULT 进入瞬间的在途命令 */
    }
    const fw_params_t *p = fw_params();
    long v = v_mm_s;
    if (v > p->vel_max) {
        v = p->vel_max;
    } else if (v < -p->vel_max) {
        v = -p->vel_max;
    }
    clamp_and_commit_velocity(v);
}

static void exec_config_set(const cart_req_t *req)
{
    int idx = fw_params_find(req->name);
    bool pole = idx == FP_POLE_ZERO_URAD || idx == FP_POLE_INV;
    if (!cm_config_set_allowed(s_mode) || !fw_params_valid(idx, req->value) ||
        ((pole || idx == FP_X_INV) && s_mode != CM_DISABLED)) {
        cartproto_send_err(req->name);
        return;
    }
    if (pole) {
        cartcal_record_t record = s_saved;
        if (idx == FP_POLE_ZERO_URAD) record.pole_zero_urad = req->value;
        else record.pole_inv = req->value;
        if (!save_record(&record)) {
            cartproto_send_err("CAL_STORAGE");
            return;
        }
    }
    fw_params_set(req->name, req->value);
    params_apply_one(req->name);
    cartproto_send_ok(req->name, req->value);
}

static void exec_config_dump(void)
{
    for (int i = 0; i < fw_params_count(); i++) {
        cartproto_send_ok(fw_params_name(i), fw_params_value(i));
    }
}

/* Only disabled: no running safety path waits behind diagnostic UART IO.
 * Keep the existing ENABLE/output mutex throughout the reads, never TX while held.
 * No writes, no implicit disable, and no attempt to read write-only IHOLD_IRUN. */
static void exec_tmc_query(void)
{
    static const uint8_t regs[] = {0x00, 0x6c, 0x02, 0x06, 0x6f};
    static const char *names[] = {"GCONF", "CHOPCONF", "IFCNT", "IOIN", "DRV_STATUS"};
    uint32_t values[5] = {0};
    bool ok[5];
    int64_t begin[5], end[5];
    xSemaphoreTake(s_output_lock, portMAX_DELAY);
    if (s_mode != CM_DISABLED || !cartaxis_peek_at_rest()) {
        xSemaphoreGive(s_output_lock);
        cartproto_send_err("TMC_BUSY");
        return;
    }
    for (unsigned i=0; i<5; ++i) {
        begin[i] = esp_timer_get_time();
        ok[i] = tmc2209_read_reg(regs[i], &values[i]);
        if (!ok[i]) values[i] = 0; /* placeholder only; validity is mandatory */
        end[i] = esp_timer_get_time();
    }
    xSemaphoreGive(s_output_lock);
    for (unsigned i=0; i<5; ++i) {
        char line[144];
        int n=snprintf(line,sizeof(line),"TMC1 %s %u %" PRIu32 " %" PRId64 " %" PRId64 "\n",
                       names[i], (unsigned)ok[i], values[i], begin[i], end[i]);
        if (n>0 && n<(int)sizeof(line)) cartproto_send_raw(line,n);
        else { cartproto_send_err("TMC_FORMAT"); return; }
    }
    cartproto_send_raw("TMC1 END\n",9);
}

static void exec_steploss_query(void)
{
    cartfsm_step_loss_diag_t d;
    xSemaphoreTake(s_output_lock, portMAX_DELAY);
    bool stopped = s_mode == CM_DISABLED || (s_mode == CM_FAULT && !s_fault_settling);
    if (!stopped) {
        xSemaphoreGive(s_output_lock);
        cartproto_send_err("STEPLOSS_BUSY");
        return;
    }
    d = s_step_loss_diag;
    xSemaphoreGive(s_output_lock);
    if (!d.valid) { cartproto_send_err("STEPLOSS_NONE"); return; }
    const magnetic_encoder_sample_t *m = &d.encoder.sample;
    bool ordered = d.c_begin_us >= 0 && d.c_end_us >= d.c_begin_us
        && d.t_compare_us >= d.c_end_us && d.t_accept_us >= d.t_compare_us;
    int64_t age = d.metadata_available && m->sampled_at_us >= 0
        && d.t_compare_us >= m->sampled_at_us ? d.t_compare_us - m->sampled_at_us : -1;
    const struct { const char *name; int64_t value; } fields[] = {
        {"VERSION",1}, {"RUN_COMPARE",d.run_at_compare}, {"RUN_ACCEPT",d.run_at_accept},
        {"T_COMPARE_US",d.t_compare_us}, {"T_ACCEPT_US",d.t_accept_us},
        {"C_BEGIN_US",d.c_begin_us}, {"C_END_US",d.c_end_us}, {"TIME_ORDER_OK",ordered},
        {"E_SENSOR_UM",d.e_sensor_um}, {"E_COMPARED_UM",d.e_compared_um},
        {"C_UM",d.c_um}, {"ERROR_UM",d.error_um}, {"THRESHOLD_UM",d.threshold_um},
        {"TARGET_ACCEPT_MM_S",d.target_at_accept_mm_s}, {"META_AVAILABLE",d.metadata_available},
        {"ENC_V_MM_S",d.encoder.velocity_mm_s}, {"ENC_V_VALID",m->velocity_valid},
        {"ENC_SPAN_US",m->velocity_span_us}, {"SAMPLE_US",m->sampled_at_us}, {"AGE_US",age},
        {"SAMPLE_SEQ",(int64_t)m->sample_seq}, {"FAILURE_SEQ",(int64_t)m->failure_seq},
        {"CONTINUITY_SEQ",(int64_t)m->continuity_seq}, {"GAP_US",m->continuous_gap_us},
        {"SAMPLE_VALID",m->valid}, {"LAST_READ_OK",m->last_attempt_ok}, {"END",1},
    };
    char line[112];
    for (unsigned i=0;i<sizeof(fields)/sizeof(fields[0]);i++) {
        int n=snprintf(line,sizeof(line),"SL1 %" PRIu32 " %s %" PRId64 "\n",
            d.event_id, fields[i].name, fields[i].value);
        if (n>0 && n<(int)sizeof(line)) cartproto_send_raw(line,n);
        else { cartproto_send_err("STEPLOSS_FORMAT"); return; }
    }
}

static void exec_cmd(const cart_req_t *req)
{
    switch (req->cmd) {
    case CART_CMD_QUERY:       exec_query(); break;
    case CART_CMD_TMC_QUERY: exec_tmc_query(); break;
    case CART_CMD_STEPLOSS_QUERY: exec_steploss_query(); break;
    case CART_CMD_CONFIRM_LEFT: exec_confirm_left(); break;
    case CART_CMD_CALIB_QUERY: exec_calib_query(); break;
    case CART_CMD_MARK_LEFT:   exec_mark_left(); break;
    case CART_CMD_MARK_RIGHT:  exec_mark_right(); break;
    case CART_CMD_ENABLE:      exec_enable(); break;
    case CART_CMD_RESET:       exec_reset(); break;
    case CART_CMD_DISABLE:     exec_disable(); break;
    case CART_CMD_VEL:         exec_vel(req->v_mm_s); break;
    case CART_CMD_CONFIG_SET:  exec_config_set(req); break;
    case CART_CMD_CONFIG_DUMP: exec_config_dump(); break;
    default:
        break;
    }
}

/* 与RESET/ENABLE/VEL同锁；旧监督快照不能关闭新一轮READY的驱动。 */
static void settle_fault(void)
{
    bool completed = false;
    cm_reason_t reason = CR_NONE;
    xSemaphoreTake(s_output_lock, portMAX_DELAY);
    if (s_mode == CM_FAULT && s_fault_settling) {
        cartaxis_halt();
        if (cartaxis_at_rest()) {
            cartaxis_enable(false);
            s_fault_settling = false;
            reason = s_reason;
            completed = true;
        }
    }
    xSemaphoreGive(s_output_lock);
    if (completed) push_mode(CM_FAULT, reason);
}

/* 只保存触发拍。E来自真正用于比较的快照，C是另一次非同步读取。 */
static bool supervise_step_loss(const fw_params_t *p)
{
    uint32_t run;
    portENTER_CRITICAL(&s_lock);
    run = s_run_id;
    portEXIT_CRITICAL(&s_lock);
    cartpos_supervision_t encoder = {0};
    bool metadata = cartpos_get_supervision(&encoder);
    long e_um = metadata ? (long)encoder.position_um : (long)cartpos_position_um();
    long sensor_e = e_um;
#ifdef CONFIG_CARTFSM_TEST_HOOKS
    e_um = consume_test_bias(e_um);
#endif
    int64_t c_begin = esp_timer_get_time();
    long c_um = (long)cartaxis_cmd_position_um();
    int64_t c_end = esp_timer_get_time();
    long threshold = p->step_loss_um;
    if (!cm_step_loss(e_um, c_um, threshold)) return false;
    cartfsm_step_loss_diag_t candidate = {
        .metadata_available = metadata, .run_at_compare = run,
        .encoder = encoder, .e_sensor_um = sensor_e, .e_compared_um = e_um,
        .c_um = c_um, .error_um = (int64_t)e_um - (int64_t)c_um,
        .threshold_um = threshold, .c_begin_us = c_begin, .c_end_us = c_end,
        .t_compare_us = esp_timer_get_time(),
    };
    enter_fault_record(CR_STEP_LOSS, &candidate);
    return true;
}

/* ---- 监督任务（1 kHz，CPU1） ---- */

static void fsm_task(void *arg)
{
    (void)arg;

    TickType_t last_wake = xTaskGetTickCount();

    bool wdt_ok = (esp_task_wdt_add(NULL) == ESP_OK);
    if (!wdt_ok) {
        ESP_LOGW(TAG, "任务看门狗订阅失败——监督任务不受监控");
    }

    for (;;) {
        const fw_params_t *p = fw_params();
        cm_mode_t mode = s_mode;

#ifdef CONFIG_CARTFSM_TEST_HOOKS
        bool a5600_ok = (s_test_enc_fail == 1) ? false : cartpos_is_ok();
        bool m6835_ok = (s_test_enc_fail == 2) ? false : poleang_is_ok();
#else
        bool a5600_ok = cartpos_is_ok();
        bool m6835_ok = poleang_is_ok();
#endif

        /* 即使处于其它故障的斜坡停机，也不依赖失效供电继续制动。 */
        if ((mode == CM_READY || mode == CM_FAULT) && !cartpower_ready()) {
            enter_power_fault();
        } else if (mode == CM_READY) {
            if (!a5600_ok || !cartpos_reference_is_valid() || !saved_track_valid()) {
                enter_fault(CR_AS5600);
            } else if (!m6835_ok) {
                enter_fault(CR_MT6835);
            } else {
                /* 丢步判定：µm 域 |E−C|（流程自测可注入 E 偏置）。
                 * 运行中堵转由它捕获；回零后抵挡块静止属正常——
                 * C 不前进、D 不增长，无误报 */
                if (supervise_step_loss(p)) {
                    /* 故障已按原路径提交；证据仅在被接受时锁存。 */
                } else {
                    /* 软限位持续钳制（运行中收紧立即生效） */
                    supervise_soft_limit(p);
                }
            }
        } else if (mode == CM_FAULT && s_fault_settling) {
            settle_fault();
        }
        /* DISABLED：无监督动作；遥测按采样有效性发送STATE/VEL_VALID。 */

        if (wdt_ok) {
            esp_task_wdt_reset();
        }
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(FSM_PERIOD_MS));
    }
}

/* ---- 公开 API ---- */

cm_mode_t cartfsm_mode(void)
{
    return s_mode;
}

cm_reason_t cartfsm_reason(void)
{
    return s_reason;
}

calib_state_t cartfsm_calib(void)
{
    return s_calib;
}

/* ---- 流程测试注入钩子（CONFIG_CARTFSM_TEST_HOOKS） ---- */
#ifdef CONFIG_CARTFSM_TEST_HOOKS

void cartfsm_test_exec(const cart_req_t *req)
{
    exec_cmd(req);
}

void cartfsm_test_inject_encoder_fail(int which)
{
    s_test_enc_fail = which;   /* 0 无、1 AS5600、2 MT6835 */
}

void cartfsm_test_inject_loss_bias(long bias_um)
{
    s_test_loss_bias_um = bias_um;
}

void cartfsm_test_reset_calib(void)
{
    s_calib = CAL_NONE;   /* 模拟上电：RAM 标定丢失 */
    s_e_left_um = 0;
    s_calib_l_um = 0;
}

#endif

esp_err_t cartfsm_start(void)
{
    if (s_started) {
        return ESP_OK;
    }

    s_output_lock = xSemaphoreCreateMutex();
    if (s_output_lock == NULL) return ESP_ERR_NO_MEM;

    /* 上电默认 DISABLED、EN 关。cartaxis_enable 的返回值仅在电机实现
     * 未初始化时非 ESP_OK，而 app_main 已先经 ESP_ERROR_CHECK(
     * motor_tmc2209_init) 完成初始化——本文件全部 EN 调用点
     * （exec_enable/exec_reset/settling）同此前提，忽略安全。 */
    cartaxis_enable(false);
    s_saved = (cartcal_record_t){
        .mm_per_rev = settings_units_per_rev(),
        .pole_zero_urad = fw_params()->pole_zero_urad,
        .pole_inv = fw_params()->pole_inv,
    };
    cartcal_record_t loaded;
    s_storage_status = cartcal_load(&loaded);
    if (s_storage_status == ESP_OK) {
        s_saved = loaded;
        fw_params_set("POLE_ZERO_URAD", loaded.pole_zero_urad);
        fw_params_set("POLE_INV", loaded.pole_inv);
    } else {
        ESP_LOGW(TAG, "未恢复标定记录: %d；需要两点标定", (int)s_storage_status);
    }
    s_calib = saved_track_valid() ? CAL_PENDING : CAL_NONE;
    s_calib_l_um = saved_track_valid() ? s_saved.length_um : 0;
    params_apply_engine();

    cartproto_register_exec(exec_cmd);

    BaseType_t ok = xTaskCreatePinnedToCore(fsm_task, "cartfsm",
                                            FSM_TASK_STACK, NULL,
                                            FSM_TASK_PRIO, NULL,
                                            FSM_TASK_CORE);
    if (ok != pdPASS) {
        ESP_LOGE(TAG, "创建监督任务失败");
        return ESP_ERR_NO_MEM;
    }

    s_started = true;
    ESP_LOGI(TAG, "模式机已启动：1 kHz，优先级 %d，CPU%d，上电 DISABLED",
             FSM_TASK_PRIO, FSM_TASK_CORE);
    return ESP_OK;
}
