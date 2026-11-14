/*
 * telemetry — 500 Hz STATE 状态流（protocol.md §数据面）
 *
 * 所有固件模式（DISABLED/READY/FAULT）在两路速度有效时发送STATE；
 * 任一路无效则仅报告VEL_VALID，不将无效缓存当作零速度。组帧经 cartproto_send_raw 上 UART0（TX 互斥共用）。
 *
 * 字段来自 cartpos_get_measurement / poleang_get_measurement：
 * 每一路的位置与速度共用同一编码器快照，名义16 ms窗口使用实际时间差。
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief 创建 500 Hz 组帧任务（CPU1、优先级 2、vTaskDelayUntil 2 ms）。
 * @return ESP_OK 或任务创建错误。
 */
esp_err_t telemetry_start(void);

/**
 * @brief 组帧纯函数（自测目标）：写入 "STATE <x> <theta> <vx> <vth>"，
 *        不含 '\n'。
 *
 * @param buf  输出缓冲。
 * @param len  缓冲大小（不足 40 字节返回负值，内容未定义）。
 * @return 写入字节数（不含 NUL）；缓冲不足返回负值。
 */
int telemetry_format_state(char *buf, size_t len, int32_t x_um,
                           int32_t theta_urad, int32_t vx_mm_s,
                           int32_t vth_mrad_s);

/** 发送侧状态，只由遥测任务使用；失败组帧不提交状态。 */
typedef struct {
    bool initialized, cart_valid, pole_valid;
    int64_t last_report_us;
} telemetry_validity_t;
/** 变化时报告VEL_VALID，所有状态每100ms报告；有效才附加原四字段STATE。 */
int telemetry_format_measurement(char *buf, size_t len, telemetry_validity_t *gate,
    int64_t now_us, bool cart_valid, bool pole_valid,
    int32_t x, int32_t theta, int32_t vx, int32_t vth);

#ifdef __cplusplus
}
#endif
