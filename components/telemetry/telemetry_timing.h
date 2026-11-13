/* STATE 调度的唯一代码常量；在 FreeRTOS.h 之后包含。 */
#pragma once

#define TELEMETRY_RATE_HZ 500

/* 编码器和监督任务要求 1 ms；STATE 周期必须是其整数倍。
 * 不允许毫秒换算截断到 0 tick，也不静默接受量化后的错误频率。
 * 默认 1000 Hz；其他能精确表达 1 ms 的 tick 频率同样允许。 */
_Static_assert(configTICK_RATE_HZ >= 1000 && configTICK_RATE_HZ % 1000 == 0,
               "telemetry requires ticks that exactly represent 1 ms");
_Static_assert(1000 % TELEMETRY_RATE_HZ == 0,
               "telemetry period must be an integer number of milliseconds");
#define TELEMETRY_PERIOD_TICKS ((TickType_t)(configTICK_RATE_HZ / TELEMETRY_RATE_HZ))
