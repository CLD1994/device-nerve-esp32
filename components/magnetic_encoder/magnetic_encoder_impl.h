/*
 * magnetic_encoder_impl — 骨架与实现接线（类别组件内部私有头）
 *
 * 采样服务负责失败计数、速度窗与原子发布；设备驱动通过回调提供
 * 读帧、每转计数与失败说明。RTOS 任务负责周期性调用采样服务。
 *
 * 实例语义：magnetic_encoder_inst_t 全部状态进实例结构，任务
 * arg=实例指针——同一实现可多实例（rev2 双 MT6835 台位）。
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "magnetic_encoder.h"
#include "magnetic_encoder_tracker.h"
#include "magnetic_encoder_core.h"
#include "magnetic_encoder_sampling.h"

#ifdef __cplusplus
extern "C" {
#endif

/** 实现回调表：薄读层的全部职责。 */
typedef struct {
    /**
     * 读一帧原始角（阻塞事务，任务上下文调用）。
     * @return true = 出参 raw 与 status 有效；false = 读取失败。
     */
    bool (*read_frame)(void *ctx, uint32_t *raw, uint8_t *status);

    /** 每转原始计数（如 4096 / 2^21），骨架传给 tracker。 */
    int32_t (*counts_per_rev)(void *ctx);

    /**
     * 失败分诊文案（进入 NOT OK 事件与首读失败的日志用）：向 buf
     * 填充单行描述（含实现的分诊细节，如失败帧原文）。可 NULL——
     * 骨架用通用文案。
     */
    void (*fail_desc)(void *ctx, char *buf, size_t len);

    /**
     * 成功样本钩子（STATUS 位告警等实现侧职责）。可 NULL。
     * 任务上下文调用，publish 之后。
     */
    void (*on_sample)(void *ctx, uint8_t status);
} magnetic_encoder_impl_t;

/** 骨架实例：契约操作表为首成员（句柄即其地址），余为骨架状态。 */
typedef struct magnetic_encoder_inst_s {
    struct magnetic_encoder_s ops;          /* 契约操作表（首成员） */
    const magnetic_encoder_impl_t *impl;    /* 实现回调表 */
    void                        *impl_ctx;  /* 实现上下文（hw 句柄等） */
    int64_t (*now_us)(void *ctx);            /* 单调时钟，读取不得阻塞 */
    void                        *clock_ctx;
    const char                  *name;      /* 任务名与日志标签（静态字符串） */

    /* 以下状态由 lock 保护，仅采样任务写、契约面读 */
    portMUX_TYPE                 lock;
    magnetic_encoder_sampling_stats_t sampling_stats;
#ifdef CONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ
    TaskHandle_t sample_task;
    esp_timer_handle_t sample_timer;
    int64_t timer_epoch_us;
    int64_t notified_at_us;
#endif
    magnetic_encoder_tracker_t   tracker;   /* 多圈累计（首样本种子） */
    int64_t                      pos_counts;
    int64_t                      sampled_at_us;
    int64_t                      continuous_gap_us;
    uint64_t                     sample_seq;
    uint64_t                     failure_seq;
    uint64_t                     continuity_seq;
    bool                         has_sample;
    bool                         last_attempt_ok;
    magnetic_encoder_vel_win_t   vel;       /* 16 ms 速度窗 */
    int32_t                      vel_counts_per_s;
    int64_t                      velocity_span_us;
    bool                         velocity_valid;
    uint32_t                     last_raw;  /* 最新单圈绝对角（类别契约与器件自测面） */
    uint8_t                      status;    /* 最新 STATUS（器件自测面） */
    magnetic_encoder_fail_t      fail;      /* 失败计数与健康位 */
} magnetic_encoder_inst_t;

/**
 * 初始化采样服务并执行首读，不创建任务。
 * 读帧与时钟由调用者提供；所有依赖及实例存储须存活到最后一次调用结束。
 * clock 必须返回启动后的单调微秒，且不得阻塞（快照锁内也会调用）。
 * 每个实例只能有一个采样调用者；sample_once 不得与初始化并发。
 * 首读失败计入 failure_seq，但不计入连续失败阈值。
 */
esp_err_t magnetic_encoder_sampler_init(magnetic_encoder_inst_t *inst,
    const magnetic_encoder_impl_t *impl, void *impl_ctx, const char *name,
    int64_t (*clock)(void *ctx), void *clock_ctx);

/**
 * 执行一次阻塞读帧、更新快照和健康状态，成功后调用设备 on_sample。
 * 返回读帧是否成功。采样失败仍更新失败序列并使速度无效。
 * 本接口用于任务调度器与驱动装配，不提供任务、频率或重试策略。
 */
bool magnetic_encoder_sampler_sample_once(magnetic_encoder_inst_t *inst);

/**
 * @brief 启动骨架：接管实例（全量重置）、首读种子、创建采样任务。
 *
 * 任务布局（契约不变量）：默认 1 kHz、可选 2 kHz、CPU1、优先级 3；任务名 = name。
 * inst 由实现层提供存储（静态或堆分配均可）；impl_ctx 生命周期
 * 须长于任务（进程级，无停机路径）。
 *
 * @return ESP_OK；参数为 NULL 或 read_frame/counts_per_rev 缺失
 *         返回 ESP_ERR_INVALID_ARG；任务创建失败返回 ESP_ERR_NO_MEM。
 */
esp_err_t magnetic_encoder_skeleton_start(magnetic_encoder_inst_t *inst,
                                          const magnetic_encoder_impl_t *impl,
                                          void *impl_ctx,
                                          const char *name);

/* 契约函数的骨架公共实现（实现层把操作表指到这里，enc 即实例） */
int32_t magnetic_encoder_inst_counts_per_rev(magnetic_encoder_handle_t enc);
uint32_t magnetic_encoder_inst_angle_counts(magnetic_encoder_handle_t enc);
int64_t  magnetic_encoder_inst_position_counts(magnetic_encoder_handle_t enc);
int32_t  magnetic_encoder_inst_velocity_counts_per_s(magnetic_encoder_handle_t enc);
bool     magnetic_encoder_inst_is_ok(magnetic_encoder_handle_t enc);
bool magnetic_encoder_inst_get_sample(magnetic_encoder_handle_t enc,
                                      magnetic_encoder_sample_t *out);

#ifdef __cplusplus
}
#endif
