/* 2 kHz构建路径与33点窗口。任务/定时器由替身隔离，不证明实际频率。 */
#include <assert.h>
#include <stdio.h>
#define ME_TIMER_TEST_CONTROLS 1
int me_timer_create_error, me_timer_start_error, me_timer_deletes;
#include <setjmp.h>
jmp_buf me_task_wait_env;
int me_task_create_error, me_task_deletes, me_task_creates, me_run_task_before_return;
int me_wdt_adds;
#include "magnetic_encoder_skeleton.c"
static int64_t now;
int64_t esp_timer_get_time(void) { return now; }
void vTaskDelay(TickType_t ticks) { now += ticks*1000; }
static int32_t cpr(void *p) {(void)p;return 2097152;}
static bool read_fail(void *p,uint32_t*r,uint8_t*s) {(void)p;(void)r;(void)s;return false;}
int main(void) {
    _Static_assert(MAGNETIC_ENCODER_HIST_LEN==33,"2 kHz需要33点");
    magnetic_encoder_inst_t inst;
    magnetic_encoder_impl_t impl={.counts_per_rev=cpr,.read_frame=read_fail};
    assert(magnetic_encoder_skeleton_start(&inst,&impl,NULL,"two_k")==ESP_OK);
    magnetic_encoder_sample_t s;
    for(int i=0;i<33;i++) {
        now=1000+i*500;
        publish_sample(&inst,100+i*50,0);
        assert(magnetic_encoder_inst_get_sample((magnetic_encoder_handle_t)&inst,&s));
        assert(s.velocity_valid==(i==32));
    }
    assert(s.velocity_span_us==16000 && s.velocity_counts_per_s==100000);
    fail_step_locked(&inst,false);
    assert(magnetic_encoder_inst_get_sample((magnetic_encoder_handle_t)&inst,&s) && !s.velocity_valid);
    for(int i=0;i<33;i++) {
        now+=1100;
        publish_sample(&inst,2000+i*50,0);
    }
    assert(magnetic_encoder_inst_get_sample((magnetic_encoder_handle_t)&inst,&s));
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
    puts("2 kHz compile/window/lifecycle checks passed");
}
