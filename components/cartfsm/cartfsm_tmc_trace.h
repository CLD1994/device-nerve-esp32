/* 可选运行期TMC只读取证。事件hook不访问UART或格式化。 */
#pragma once
#include <stdint.h>
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
#ifdef CONFIG_CARTFSM_TMC_TRACE
void cartfsm_tmc_trace_start(void);
void cartfsm_tmc_trace_begin_run(uint32_t run,int64_t now);
void cartfsm_tmc_trace_event(uint32_t run,uint32_t event,int64_t now);
void cartfsm_tmc_trace_query(void);
#else
static inline void cartfsm_tmc_trace_start(void) {}
static inline void cartfsm_tmc_trace_begin_run(uint32_t run,int64_t now){(void)run;(void)now;}
static inline void cartfsm_tmc_trace_event(uint32_t run,uint32_t event,int64_t now){(void)run;(void)event;(void)now;}
#endif
