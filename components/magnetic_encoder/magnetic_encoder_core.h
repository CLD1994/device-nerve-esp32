/*
 * magnetic_encoder_core — 骨架纯函数（类别组件内部接口）
 *
 * 失败计数状态机与名义 16 ms 速度窗。速度窗保留 17 个成功
 * 样本，用实际时间差换算；未满窗、时间异常和数值溢出均显式无效。
 *
 * 纯逻辑，无硬件/RTOS 依赖，宿主可测（host_tests/
 * magnetic_encoder_core_test.c）。
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 连续读失败达到该值 → NOT OK（契约不变量 3） */
#define MAGNETIC_ENCODER_FAIL_LIMIT   10

/* 速度窗：16 ms（17 个 1 ms 位置样本，环形缓冲） */
#define MAGNETIC_ENCODER_MAX_VELOCITY_SPAN_US 32000
#define MAGNETIC_ENCODER_SPEED_WINDOW 16
#define MAGNETIC_ENCODER_HIST_LEN     (MAGNETIC_ENCODER_SPEED_WINDOW + 1)

/* ---- 失败计数状态机 ---- */

typedef struct {
    int  streak;   /* 当前连续失败数 */
    bool ok;       /* 契约可见健康位 */
} magnetic_encoder_fail_t;

/** 健康初值：streak=0、ok=true（开机尚未失败即健康）。 */
void magnetic_encoder_fail_reset(magnetic_encoder_fail_t *f);

/**
 * @brief 喂入一次读取结果，推进状态机。
 *
 * @return true = 本步发生状态迁移事件（streak 首达 LIMIT 进入
 *         NOT OK，或 NOT OK 期间首次成功恢复）——调用方借此打
 *         一次日志；平稳步返回 false。
 */
bool magnetic_encoder_fail_step(magnetic_encoder_fail_t *f, bool read_ok);

/* ---- 16 ms 速度窗 ---- */

typedef struct {
    int64_t hist[MAGNETIC_ENCODER_HIST_LEN];   /* 环形位置样本 */
    int64_t time_us[MAGNETIC_ENCODER_HIST_LEN];
    int     head;                              /* 最新样本下标 */
    int     fill;                              /* 已存样本数（≤ 窗长） */
} magnetic_encoder_vel_win_t;

/** 清空窗口（重新预热）。 */
void magnetic_encoder_vel_win_reset(magnetic_encoder_vel_win_t *w);

typedef struct {
    int32_t counts_per_s; /* 仅 valid 时可用于控制或停稳判断 */
    int64_t span_us;      /* 最新样本与最旧样本之间的实际时间 */
    bool valid;
} magnetic_encoder_velocity_t;

/**
 * 推入读帧完成时间与累计位置。保留 17 个样本；时间必须非负且递增。
 * 非递增时间或相邻间隔大于 max_gap_us 时清窗，以当前样本重新播种。
 * 读取失败由调用方 reset；总跨度超过32ms或算术越界返回 invalid，
 * 不截断为伪低速。总跨度超限保留滑窗，旧慢样本淘汰后自然恢复。
 */
magnetic_encoder_velocity_t magnetic_encoder_vel_push_at(
    magnetic_encoder_vel_win_t *w, int64_t pos, int64_t time_us,
    int64_t max_gap_us);

#ifdef __cplusplus
}
#endif
