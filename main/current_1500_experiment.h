#pragma once
/* Experimental, boot-only substitution. Never changes settings/NVS.
 * Do not reinterpret a different device configuration. */
static inline int current_1500_experiment_run(int run_ma, int hold_ma, float rsense)
{
    return run_ma == 800 && hold_ma == 400 && rsense >= 0.10999f && rsense <= 0.11001f
        ? 1500 : run_ma;
}
