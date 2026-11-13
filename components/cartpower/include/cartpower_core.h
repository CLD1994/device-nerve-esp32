#pragma once
#include <stdbool.h>
#include <stdint.h>
/* 纯状态机；时间单位µs。失败锁定，只能重新初始化。 */
typedef enum { CP_WAITING, CP_VERIFIED, CP_FAILED } cp_state_t;
typedef enum { CP_NONE, CP_INIT, CP_REQUEST, CP_READ, CP_ADC, CP_TIMEOUT,
               CP_PD, CP_VOLTAGE, CP_STALE } cp_reason_t;
typedef struct {
    int64_t settle_us, timeout_us, sample_us;
    unsigned stable_required;
    int64_t fresh_us;
} cp_timing_t;
typedef struct {
    cp_state_t state;
    cp_reason_t reason;
    cp_timing_t timing;
    int64_t started_us, last_sample_us;
    unsigned stable_samples;
} cp_core_t;
void cp_init(cp_core_t *s, const cp_timing_t *timing, int64_t now);
void cp_fail(cp_core_t *s, cp_reason_t reason);
void cp_sample(cp_core_t *s, int64_t now, int64_t sampled_at,
               bool read_ok, bool pd, int vbus_mv);
/* 检查新鲜度并锁定过期状态；调用方串行保护。 */
bool cp_allowed(cp_core_t *s, int64_t now);
