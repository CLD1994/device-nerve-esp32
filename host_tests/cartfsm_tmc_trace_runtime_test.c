#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include "../components/cartfsm/cartfsm_tmc_trace.h"
#include "tmc2209.h"
#include "cartfsm.h"
#include "freertos/task.h"
static void (*task_fn)(void*);
static jmp_buf stop;
static int64_t now;
static unsigned reads, create_calls;
static bool fail_create, change_run;
static cm_mode_t mode=CM_DISABLED;
cm_mode_t cartfsm_mode(void){return mode;}
static char output[32768], error[64];
static size_t used;
BaseType_t xTaskCreatePinnedToCore(void (*fn)(void*),const char*n,unsigned stack,void*a,unsigned prio,void*h,unsigned core) {
    (void)n;(void)a;(void)h;assert(stack>=2048 && prio==1 && core==0);
    ++create_calls;task_fn=fn;return fail_create?0:pdPASS;
}
void vTaskDelay(TickType_t t) {assert(t==50);longjmp(stop,1);}
int64_t esp_timer_get_time(void){return now;}
tmc2209_read_result_t tmc2209_try_read_drv_status(uint32_t*out) {
    ++reads;*out=0x80000000;now+=1000;
    if(change_run)cartfsm_tmc_trace_begin_run(2,now);
    return TMC2209_READ_OK;
}
void cartproto_send_raw(const char*s,int n){assert(used+(size_t)n<sizeof(output));memcpy(output+used,s,n);used+=n;output[used]=0;}
void cartproto_send_err(const char*s){snprintf(error,sizeof(error),"%s",s);}
static void poll(void){if(setjmp(stop)==0)task_fn(NULL);}
int main(void){
    cartfsm_tmc_trace_query();assert(!strcmp(error,"TMCTRACE_UNAVAILABLE"));
    fail_create=true;cartfsm_tmc_trace_start();assert(create_calls==1);
    cartfsm_tmc_trace_query();assert(!strcmp(error,"TMCTRACE_UNAVAILABLE"));
    fail_create=false;cartfsm_tmc_trace_start();assert(create_calls==2);
    cartfsm_tmc_trace_query();assert(!strcmp(error,"TMCTRACE_NONE"));
    poll();assert(reads==0);
    now=1000000;cartfsm_tmc_trace_begin_run(1,now);poll();assert(reads==0);
    mode=CM_READY;poll();assert(reads==1);
    now=1100000;cartfsm_tmc_trace_event(1,9,now);cartfsm_tmc_trace_query();assert(!strcmp(error,"TMCTRACE_BUSY"));
    now=1200000;change_run=true;poll();change_run=false; /* across-run read is dropped */
    used=0;cartfsm_tmc_trace_query();
    assert(strstr(output,"TMCT1 BEGIN 9 1 1100000 2 1 1 50000 5000000 1201000\n"));
    assert(strstr(output,"TMCT1 END 9 1\n"));
    now=2000000;cartfsm_tmc_trace_event(2,10,now);
    mode=CM_DISABLED;now=7000000;unsigned before=reads;poll();assert(reads==before);used=0;cartfsm_tmc_trace_query();
    assert(strstr(output,"TMCT1 BEGIN 10 2 2000000 1 0 0 50000 5000000 7000000\n"));
    puts("TMC trace runtime: all assertions passed");
}
