/* 生产调度常量的编译契约：可用 tick 保持 500 Hz，误配置必须拒绝。 */
#include <assert.h>
#include <stdint.h>
#ifndef TEST_TICK_HZ
#define TEST_TICK_HZ 1000
#endif
typedef uint32_t TickType_t;
#define configTICK_RATE_HZ TEST_TICK_HZ
#include "telemetry_timing.h"
int main(void)
{
    assert(TELEMETRY_RATE_HZ == 500);
    assert(TELEMETRY_PERIOD_TICKS > 0);
    assert(TELEMETRY_PERIOD_TICKS * TELEMETRY_RATE_HZ == TEST_TICK_HZ);
    return 0;
}
