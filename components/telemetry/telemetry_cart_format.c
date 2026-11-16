/* 独立小车诊断流：20 ms最小组帧间隔，不改变双路STATE门控。 */
#include "telemetry.h"
#include <inttypes.h>
#include <stdio.h>
int telemetry_format_cart(char *buf, size_t len, telemetry_cart_gate_t *gate,
    int64_t now_us, bool valid, int64_t sample_us, uint64_t seq,
    int32_t x_um, int32_t vx_mm_s)
{
#ifndef CONFIG_TELEMETRY_CART_DIAGNOSTICS
    (void)buf;(void)len;(void)gate;(void)now_us;(void)valid;
    (void)sample_us;(void)seq;(void)x_um;(void)vx_mm_s;
    return 0;
#else
    if(!buf || !gate || !len || now_us<0) return -1;
    if(gate->initialized) {
        if(now_us<gate->last_report_us) {
            gate->last_report_us=now_us; /* 重基但本次不发送；绝不追赶。 */
            return 0;
        }
        if(now_us-gate->last_report_us<20000) return 0;
    }
    if(valid && (sample_us<0 || sample_us>now_us || seq==0)) return -1;
    int n;
    if(valid) n=snprintf(buf,len,"CART_STATE1 %" PRId64 " %" PRId64 " %" PRIu64 " 1 %" PRId32 " %" PRId32 "\n",
        now_us,sample_us,seq,x_um,vx_mm_s);
    else n=snprintf(buf,len,"CART_STATE1 %" PRId64 " 0\n",now_us);
    if(n<0 || (size_t)n>=len) return -1;
    *gate=(telemetry_cart_gate_t){.initialized=true,.last_report_us=now_us};
    return n;
#endif
}
