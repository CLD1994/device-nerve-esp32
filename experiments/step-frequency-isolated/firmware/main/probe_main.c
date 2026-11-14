/* Diagnostic-only entry. No motor driver, PD negotiation, production FSM or ENABLE. */
#include "probe_control.h"
#include "sdkconfig.h"
#if !defined(CONFIG_ESP_MAIN_TASK_AFFINITY_CPU0) || !CONFIG_ESP_MAIN_TASK_AFFINITY_CPU0
#error "Isolated STEP probe requires app_main pinned to CPU0"
#endif
#include "step_engine.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_timer.h"
#include "esp_task_wdt.h"
#include "esp_app_desc.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdio.h>
#include <string.h>

#define STEP_PIN 5
#define DIR_PIN 6
#define EN_PIN 21
#define PORT UART_NUM_0
static probe_control ctl;
static uint32_t count_start;
static uint64_t ended;
static bool report;

static void finish(void) {
    step_engine_stop();
    gpio_set_level(STEP_PIN,0);
    ended=(uint64_t)esp_timer_get_time();
    report=true;
}
static void fault(const char *why) {
    probe_fault(&ctl,why);
    finish();
}
static void supervise(void) {
    probe_action a=probe_tick(&ctl,(uint64_t)esp_timer_get_time(),gpio_get_level(EN_PIN)==1);
    if(a==ACTION_STOP) finish();
    else if(a==ACTION_FEED) step_engine_vel_target((int64_t)ctl.hz*65536);
}
static void command(const char *line) {
    probe_command c=probe_parse(line);
    if(c.kind==CMD_STOP) {probe_stop(&ctl);finish();return;}
    if(c.kind==CMD_INFO) {report=true;return;}
    if(c.kind!=CMD_RUN) {fault("INVALID_COMMAND");return;}
    if(ctl.state!=PROBE_IDLE) {fault("RUN_NOT_IDLE");return;}
    if(!probe_start(&ctl,c,(uint64_t)esp_timer_get_time(),gpio_get_level(EN_PIN)==1)) {finish();return;}
    count_start=(uint32_t)step_engine_position_steps();
    /* Approximate 100 ms ramp. This also avoids the low-target, huge-accel
       startup corner. The requested duration INCLUDES ramp, not just plateau. */
    step_engine_vel_set_accel(c.hz*10);
    step_engine_vel_set_decel(c.hz*10);
    step_engine_vel_set_wdt_us(100000);
    /* No UART output during generation: independent monotonic deadline wins. */
    supervise();
    if(ctl.state==PROBE_RUNNING) step_engine_vel_target((int64_t)c.hz*65536);
}
static void output(void) {
    if(!report || ctl.state==PROBE_RUNNING)return;
    char text[384];
    uint32_t count=(uint32_t)step_engine_position_steps()-count_start;
    int n=snprintf(text,sizeof(text),"STEP_PROBE state=%d reason=%s EN=%d hz=%lu elapsed_us=%llu software_steps=%lu IDF=%s build=%s\r\n",
        ctl.state,ctl.reason?ctl.reason:"BOOT_IDLE",gpio_get_level(EN_PIN),
        (unsigned long)ctl.hz,(unsigned long long)(ended>=ctl.started?ended-ctl.started:0),
        (unsigned long)count,esp_get_idf_version(),esp_app_get_description()->version);
    /* Blocking serial output is permitted ONLY after STEP has stopped. */
    uart_write_bytes(PORT,text,n);
    report=false;
}
void app_main(void) {
    gpio_config_t en={.pin_bit_mask=1ULL<<EN_PIN,.mode=GPIO_MODE_INPUT_OUTPUT};
    /* Preload high before enabling the output; reset-time electrical isolation
       still requires the external wiring precautions in the README. */
    ESP_ERROR_CHECK(gpio_set_level(EN_PIN,1));
    ESP_ERROR_CHECK(gpio_config(&en));
    ESP_ERROR_CHECK(gpio_set_level(EN_PIN,1));
    gpio_config_t pins={.pin_bit_mask=(1ULL<<STEP_PIN)|(1ULL<<DIR_PIN),.mode=GPIO_MODE_OUTPUT};
    ESP_ERROR_CHECK(gpio_config(&pins));
    ESP_ERROR_CHECK(gpio_set_level(STEP_PIN,0));
    ESP_ERROR_CHECK(gpio_set_level(DIR_PIN,0));
    uart_config_t u={.baud_rate=460800,.data_bits=UART_DATA_8_BITS,.parity=UART_PARITY_DISABLE,
        .stop_bits=UART_STOP_BITS_1,.flow_ctrl=UART_HW_FLOWCTRL_DISABLE,.source_clk=UART_SCLK_DEFAULT};
    QueueHandle_t events;
    ESP_ERROR_CHECK(uart_param_config(PORT,&u));
    ESP_ERROR_CHECK(uart_set_pin(PORT,43,44,UART_PIN_NO_CHANGE,UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_driver_install(PORT,1024,0,16,&events,0));
    /* This application deliberately restricts all engine API calls to the
       CPU0 app_main task. GPTimer interrupt allocation occurs on that same
       core. This is NOT a fix or proof for production cross-core stop races. */
    if(xPortGetCoreID()!=0) ESP_ERROR_CHECK(ESP_ERR_INVALID_STATE);
    ESP_ERROR_CHECK(step_engine_init(STEP_PIN,DIR_PIN));
    ESP_ERROR_CHECK(esp_task_wdt_add(NULL));
    report=true;
    char line[80];size_t used=0;
    for(;;) {
        supervise(); /* Always before parsing or output. */
        uart_event_t ev;
        for(int i=0;i<16 && xQueueReceive(events,&ev,0)==pdTRUE;i++) {
            if(ev.type==UART_FIFO_OVF||ev.type==UART_BUFFER_FULL||ev.type==UART_PARITY_ERR||ev.type==UART_FRAME_ERR||ev.type==UART_BREAK)fault("UART_ERROR");
        }
        unsigned char bytes[64];
        int n=uart_read_bytes(PORT,bytes,sizeof(bytes),0);
        if(n<0)fault("UART_READ");
        for(int i=0;i<n;i++) {
            supervise();
            unsigned char b=bytes[i];
            if(b=='\r')continue;
            if(b=='\n') {line[used]=0;command(line);used=0;}
            else if(b<32||b>126||used>=sizeof(line)-1) {used=0;fault("UART_LINE");}
            else line[used++]=(char)b;
        }
        supervise();
        output();
        ESP_ERROR_CHECK(esp_task_wdt_reset());
        vTaskDelay(1);
    }
}
