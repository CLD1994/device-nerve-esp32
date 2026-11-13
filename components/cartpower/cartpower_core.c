#include "cartpower_core.h"
void cp_init(cp_core_t *s, const cp_timing_t *timing, int64_t now)
{
    *s = (cp_core_t){ .state=CP_WAITING, .timing=*timing,
                     .started_us=now, .last_sample_us=now-timing->sample_us };
}
void cp_fail(cp_core_t *s, cp_reason_t reason)
{
    if (s->state == CP_FAILED) return;
    s->state=CP_FAILED;
    s->reason=reason;
    s->stable_samples=0;
}
bool cp_allowed(cp_core_t *s, int64_t now)
{
    if (s->state == CP_WAITING && now-s->started_us >= s->timing.timeout_us)
        cp_fail(s,CP_TIMEOUT);
    if (s->state == CP_VERIFIED &&
        (now < s->last_sample_us || now-s->last_sample_us > s->timing.fresh_us))
        cp_fail(s,CP_STALE);
    return s->state==CP_VERIFIED;
}
void cp_sample(cp_core_t *s, int64_t now, int64_t sampled_at,
               bool read_ok, bool pd, int vbus_mv)
{
    (void)cp_allowed(s,now);
    if (s->state==CP_FAILED) return;
    if (!read_ok) { cp_fail(s,CP_READ); return; }
    if (vbus_mv < 0) { cp_fail(s,CP_ADC); return; }
    if (vbus_mv > 21500) { cp_fail(s,CP_VOLTAGE); return; }
    if (sampled_at > now || now-sampled_at > s->timing.fresh_us) {
        cp_fail(s,CP_STALE); return;
    }
    if (s->state==CP_VERIFIED) {
        if (!pd) cp_fail(s,CP_PD);
        else if (vbus_mv<19000 || vbus_mv>21000) cp_fail(s,CP_VOLTAGE);
        else s->last_sample_us=sampled_at;
        return;
    }
    if (now-s->started_us < s->timing.settle_us ||
        sampled_at-s->last_sample_us < s->timing.sample_us) return;
    if (sampled_at-s->last_sample_us > s->timing.fresh_us) s->stable_samples=0;
    s->last_sample_us=sampled_at;
    if (pd && vbus_mv>=19000 && vbus_mv<=21000) ++s->stable_samples;
    else s->stable_samples=0;
    if (s->stable_samples>=s->timing.stable_required) s->state=CP_VERIFIED;
}
