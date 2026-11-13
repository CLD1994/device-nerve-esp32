/*
 * magnetic_encoder — 绝对式磁编码器类别契约（句柄式多实例）
 *
 * 原生单位原则：契约只含 counts 与每转计数，不出现机械单位
 * （mm、µrad）与已标定角度——换算归解释层（cartpos / poleang）。
 * 命名与 count / accumulator 词汇参考 espp/magnetic_encoder。
 *
 * 多实例分发：每个实现把操作表（struct magnetic_encoder_s）作为
 * 实例结构的首成员，init 返回其地址；契约函数经操作表分发到所属
 * 实现——本台位 AS5600 与 MT6835 两实例同时编入并存，同一组契约
 * 函数按句柄各归其主。
 * 语义：docs/superpowers/specs/2026-10-14-device-category-abstraction.md。
 */
#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct magnetic_encoder_s *magnetic_encoder_handle_t;

/** 连续采样允许的最大成功样本间隔，微秒。 */
#define MAGNETIC_ENCODER_MAX_CONTINUOUS_GAP_US 20000

/** 同一临界区内取得的采样快照；时间单位为启动后的单调微秒。 */
typedef struct {
    int64_t position_counts;
    int64_t sampled_at_us;       /* 最近成功样本的时间，仅 valid 时有意义 */
    uint64_t sample_seq;         /* 每次成功递增 */
    uint64_t continuity_seq;     /* 成功样本间隔超过连续性上限时递增 */
    uint64_t failure_seq;        /* 每次失败递增，包括首读失败 */
    bool valid;                 /* 已有至少一个成功样本，不等价于新鲜 */
    bool last_attempt_ok;       /* 最近一次读帧是否成功 */
    bool ok;                    /* 原 is_ok 连续失败阈值状态 */
} magnetic_encoder_sample_t;

/** 操作表：实现填写类别函数指针；必须作为实例结构的首成员。 */
struct magnetic_encoder_s {
    int32_t (*counts_per_rev)(magnetic_encoder_handle_t enc);
    uint32_t (*angle_counts)(magnetic_encoder_handle_t enc);
    int64_t  (*position_counts)(magnetic_encoder_handle_t enc);
    int32_t  (*velocity_counts_per_s)(magnetic_encoder_handle_t enc);
    bool     (*is_ok)(magnetic_encoder_handle_t enc);
    bool     (*get_sample)(magnetic_encoder_handle_t enc, magnetic_encoder_sample_t *out);
};

/**
 * 原子取得位置、成功时间和采样状态。返回 false 表示参数或实现不支持，
 * 此时不修改 out；返回 true 不保证 valid、last_attempt_ok 或数据新鲜。
 */
static inline bool magnetic_encoder_get_sample(magnetic_encoder_handle_t enc,
                                                magnetic_encoder_sample_t *out)
{
    return enc != 0 && out != 0 && enc->get_sample != 0
        && enc->get_sample(enc, out);
}

/** 每转原始计数（分辨率）：AS5600 为 4096，MT6835 为 2097152。 */
static inline int32_t magnetic_encoder_counts_per_rev(magnetic_encoder_handle_t enc)
{
    return enc->counts_per_rev(enc);
}

/**
 * @brief 最近一次有效采样的单圈绝对角，范围 [0, counts_per_rev)。
 *
 * 保留器件零位，不以启动姿态归零；方向沿实现配置（例如 AS5600
 * 的 invert_dir），不是保证未经处理的寄存器值。首样本前缓存为 0，
 * 读失败保留上次采样值。数值不携带有效性；is_ok 是连续读取失败
 * 阈值状态，初始为 true，不能证明已有有效样本或数据新鲜。
 */
static inline uint32_t magnetic_encoder_angle_counts(magnetic_encoder_handle_t enc)
{
    return enc->angle_counts(enc);
}

/**
 * @brief 多圈累计位置（accumulator：原始 counts，带符号，原生方向，
 *        自 init 累计）；首样本前为 0。
 *
 * int64 承载：连续单方向旋转不溢出。混叠上界：unwrap 以
 * ±每转计数/2 为阈值，单个采样周期内转过超过半转即混叠——本值
 * 与速度估计都不可信（AS5600 @1 kHz 上界约 122 rev/s，MT6835
 * 约 403 rev/s，远高于本台位物理速度）。
 */
static inline int64_t magnetic_encoder_position_counts(magnetic_encoder_handle_t enc)
{
    return enc->position_counts(enc);
}

/** 角速度估计（counts/s，16 窗均值）。量子 62.5 counts/s；窗口未满为 0。 */
static inline int32_t magnetic_encoder_velocity_counts_per_s(magnetic_encoder_handle_t enc)
{
    return enc->velocity_counts_per_s(enc);
}

/** 连续 ≥10 次读取失败为 false；一次成功即恢复 true。 */
static inline bool magnetic_encoder_is_ok(magnetic_encoder_handle_t enc)
{
    return enc->is_ok(enc);
}

#ifdef __cplusplus
}
#endif
