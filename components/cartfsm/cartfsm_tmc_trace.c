#include "cartfsm_tmc_trace.h"
#ifdef CONFIG_CARTFSM_TMC_TRACE
#include "cartfsm_tmc_trace_core.h"
#include "cartproto.h"
#include "cartfsm.h"
#include "tmc2209.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <inttypes.h>
#include <stdio.h>
static portMUX_TYPE trace_lock=portMUX_INITIALIZER_UNLOCKED;
static tmc_trace_core_t capture;
static bool available;
static void poll_once(void) {
    int64_t now=esp_timer_get_time();
    portENTER_CRITICAL(&trace_lock);
    tmc_trace_core_tick(&capture,now);
    uint32_t run=capture.run;
    bool ended=capture.latched && capture.header.state!=0;
    bool tail=capture.valid && capture.header.state==0;
    portEXIT_CRITICAL(&trace_lock);
    if(!run || ended || (!tail && cartfsm_mode()!=CM_READY))return;
    tmc_trace_row_t row={.begin_us=esp_timer_get_time()};
    /* 无FSM输出锁：只读DRV_STATUS，UART忙时直接留busy记录。 */
    row.status=(uint32_t)tmc2209_try_read_drv_status(&row.raw);
    row.end_us=esp_timer_get_time();
    portENTER_CRITICAL(&trace_lock);
    tmc_trace_core_sample(&capture,run,&row);
    portEXIT_CRITICAL(&trace_lock);
}
static void task(void *arg) {
    (void)arg;
    for(;;){poll_once();vTaskDelay(pdMS_TO_TICKS(50));} /* 不追赶迟到的采样 */
}
void cartfsm_tmc_trace_start(void) {
    if(available)return;
    available=xTaskCreatePinnedToCore(task,"tmc_trace",3072,NULL,1,NULL,0)==pdPASS;
}
void cartfsm_tmc_trace_begin_run(uint32_t run,int64_t now) {
    portENTER_CRITICAL(&trace_lock);
    tmc_trace_core_begin_run(&capture,run,now);
    portEXIT_CRITICAL(&trace_lock);
}
void cartfsm_tmc_trace_event(uint32_t run,uint32_t event,int64_t now) {
    portENTER_CRITICAL(&trace_lock);
    tmc_trace_core_trigger(&capture,run,event,now);
    portEXIT_CRITICAL(&trace_lock);
}
static bool send_line(char *line,int n,size_t cap) {
    if(n<=0 || (size_t)n>=cap){cartproto_send_err("TMCTRACE_FORMAT");return false;}
    cartproto_send_raw(line,n);return true;
}
void cartfsm_tmc_trace_query(void) {
    if(!available){cartproto_send_err("TMCTRACE_UNAVAILABLE");return;}
    portENTER_CRITICAL(&trace_lock);
    const tmc_trace_header_t *p=tmc_trace_core_header(&capture);
    bool valid=p!=NULL;
    tmc_trace_header_t h=valid?*p:(tmc_trace_header_t){0};
    portEXIT_CRITICAL(&trace_lock);
    if(!valid){cartproto_send_err("TMCTRACE_NONE");return;}
    if(!h.state){cartproto_send_err("TMCTRACE_BUSY");return;}
    char line[256];
    int n=snprintf(line,sizeof(line),"TMCT1 BEGIN %"PRIu32" %"PRIu32" %"PRId64" %u %u %u %"PRId64" %"PRId64" %"PRId64"\n",
        h.event_id,h.run_id,h.event_us,h.state,h.count,h.pre_count,TMC_TRACE_PERIOD_US,TMC_TRACE_POST_US,h.ended_us);
    if(!send_line(line,n,sizeof(line)))return;
    for(unsigned i=0;i<h.count;i++) {
        tmc_trace_row_t row;
        portENTER_CRITICAL(&trace_lock);
        bool same=capture.valid && capture.header.event_id==h.event_id && capture.header.run_id==h.run_id;
        bool got=same && tmc_trace_core_row(&capture,i,&row);
        portEXIT_CRITICAL(&trace_lock);
        if(!got){cartproto_send_err("TMCTRACE_CHANGED");return;}
        n=snprintf(line,sizeof(line),"TMCT1 ROW %"PRIu32" %u %"PRIu64" %"PRId64" %"PRId64" %"PRIu32" %"PRIu32"\n",
            h.event_id,i,row.seq,row.begin_us,row.end_us,row.status,row.raw);
        if(!send_line(line,n,sizeof(line)))return;
    }
    n=snprintf(line,sizeof(line),"TMCT1 END %"PRIu32" %u\n",h.event_id,h.count);
    (void)send_line(line,n,sizeof(line));
}
#endif
