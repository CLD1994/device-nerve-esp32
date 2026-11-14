#include <assert.h>
#include <stdio.h>
#include "magnetic_encoder_sampling.h"
int main(void) {
    int64_t cycle=-1; uint64_t missed=0;
    assert(magnetic_encoder_sampling_due(1000,1000,&cycle,&missed));
    assert(!magnetic_encoder_sampling_due(1000,1001,&cycle,&missed));
    assert(!magnetic_encoder_sampling_due(1000,999,&cycle,&missed));
    assert(magnetic_encoder_sampling_due(1000,1000+4*ME_SAMPLE_PERIOD_US,&cycle,&missed));
    assert(missed==3);
    assert(!magnetic_encoder_sampling_due(1000,1000+4*ME_SAMPLE_PERIOD_US,&cycle,&missed));
    magnetic_encoder_sampling_stats_t s={0};
    magnetic_encoder_sampling_record(&s,1000,1100,1200,900,true);
    magnetic_encoder_sampling_record(&s,2000,3100,3300,1900,false);
    magnetic_encoder_sampling_record(&s,4000,4100,4200,3800,true);
    assert(s.attempts==3 && s.failures==1);
    assert(s.read_overruns==1 && s.work_overruns==1);
    assert(s.success_interval_min_us==3000 && s.success_interval_max_us==3000);
    assert(s.read_max_us==1100 && s.work_max_us==1300 && s.wake_max_us==200);
    puts("sampling schedule/stats passed");
}
