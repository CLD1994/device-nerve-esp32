/* 2 kHz构建路径与33点窗口。任务/定时器由替身隔离，不证明实际频率。 */
#include <assert.h>
#include <stdio.h>
int me_timer_create_error, me_timer_start_error, me_timer_deletes;
#include <setjmp.h>
jmp_buf me_task_wait_env;
int me_task_create_error, me_task_deletes, me_task_creates, me_run_task_before_return;
int me_wdt_adds;
#include "magnetic_encoder_impl.h"
void (*me_created_task)(void *);
void *me_created_task_arg;
uint32_t (*me_notify_take)(TickType_t);
static int64_t now;
int64_t esp_timer_get_time(void) { return now; }
void vTaskDelay(TickType_t ticks) { now += ticks*1000; }
static int32_t cpr(void *p) {(void)p;return 2097152;}
static bool frame_ok;
static uint32_t frame_raw;
static bool read_frame(void *p,uint32_t*r,uint8_t*s) { (void)p; *r=frame_raw; *s=0; return frame_ok; }
static int waits;
static uint32_t scheduled_notification(TickType_t wait)
{
    if (!wait) return 0; /* No pending notification after the read. */
    switch (++waits) {
    case 1: now=500; frame_raw=10; return 1;
    case 2: now=500; frame_raw=20; return 1; /* Duplicate cycle: no read. */
    case 3: now=2000; frame_raw=30; return 3; /* Coalesced: one read. */
    default: longjmp(me_task_wait_env,1);
    }
}
int main(void) {
    static magnetic_encoder_inst_t inst;
    magnetic_encoder_impl_t impl={.counts_per_rev=cpr,.read_frame=read_frame};
    assert(magnetic_encoder_skeleton_start(&inst,&impl,NULL,"two_k")==ESP_OK);
    magnetic_encoder_sample_t s;
    for(int i=0;i<33;i++) {
        now=1000+i*500;
        frame_ok=true; frame_raw=100+i*50;
        assert(magnetic_encoder_sampler_sample_once(&inst));
        assert(magnetic_encoder_get_sample((magnetic_encoder_handle_t)&inst,&s));
        assert(s.velocity_valid==(i==32));
    }
    assert(s.velocity_span_us==16000 && s.velocity_counts_per_s==100000);
    frame_ok=false;
    assert(!magnetic_encoder_sampler_sample_once(&inst));
    assert(magnetic_encoder_get_sample((magnetic_encoder_handle_t)&inst,&s) && !s.velocity_valid);
    for(int i=0;i<33;i++) {
        now+=1100;
        frame_ok=true; frame_raw=2000+i*50;
        assert(magnetic_encoder_sampler_sample_once(&inst));
    }
    assert(magnetic_encoder_get_sample((magnetic_encoder_handle_t)&inst,&s));
    assert(!s.velocity_valid && s.velocity_span_us==35200);
    me_timer_create_error=ESP_ERR_INVALID_ARG;
    int creates=me_task_creates;
    assert(magnetic_encoder_skeleton_start(&inst,&impl,NULL,"two_k")==ESP_ERR_INVALID_ARG);
    assert(me_task_creates==creates);
    me_timer_create_error=0; me_task_create_error=1;
    assert(magnetic_encoder_skeleton_start(&inst,&impl,NULL,"two_k")==ESP_ERR_NO_MEM);
    assert(me_timer_deletes==1);
    me_task_create_error=0; me_timer_start_error=ESP_ERR_INVALID_ARG;
    me_run_task_before_return=1; /* 任务先运行到等待点，定时器随后启动失败。 */
    assert(magnetic_encoder_skeleton_start(&inst,&impl,NULL,"two_k")==ESP_ERR_INVALID_ARG);
    assert(me_timer_deletes==2 && me_task_deletes==1 && me_wdt_adds==0);
    me_run_task_before_return=0; me_timer_start_error=0;
    now=0; frame_ok=false;
    assert(magnetic_encoder_skeleton_start(&inst,&impl,NULL,"two_k")==ESP_OK);
    frame_ok=true; me_notify_take=scheduled_notification;
    if (setjmp(me_task_wait_env)==0) me_created_task(me_created_task_arg);
    me_notify_take=NULL;
    assert(magnetic_encoder_get_sample((magnetic_encoder_handle_t)&inst,&s));
    assert(s.sample_seq==2 && s.raw_counts==30 && s.position_counts==20);
    assert(s.sampled_at_us==2000 && s.last_attempt_ok);
    assert(me_wdt_adds==1);
    puts("2 kHz scheduling/window/lifecycle checks passed");
}
