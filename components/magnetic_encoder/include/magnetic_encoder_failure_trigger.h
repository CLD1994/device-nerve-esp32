/* One-shot read-failure trigger. Owned by the sampling task; no implicit rearm. */
#pragma once
#include <stdbool.h>
typedef struct {
    bool armed, latched;
    void (*raise)(void *context);
    void *context;
} me_failure_trigger_t;
static inline void me_failure_trigger_valid(me_failure_trigger_t *t, bool valid)
{
    if (valid && !t->latched) t->armed = true;
}
static inline void me_failure_trigger_read_done(me_failure_trigger_t *t, bool success)
{
    if (!success && t->armed && !t->latched) {
        t->latched = true;
        t->raise(t->context);
    }
}
