#include <assert.h>
#include <stdio.h>
#define ESP_LOGD(...) ((void)0)
#include "../components/tmc2209/tmc2209.c"
#include "../main/current_1500_experiment.h"
static uint32_t registers[128];
static unsigned en_calls;
bool tmc2209_write_reg(uint8_t r,uint32_t v) { registers[r]=v;return true; }
bool tmc2209_read_reg(uint8_t r,uint32_t*v) { *v=registers[r];return true; }
esp_err_t tmc2209_hw_init(const tmc2209_hw_config_t *c) {(void)c;return ESP_OK;}
esp_err_t gpio_set_level(gpio_num_t p,unsigned v) {(void)p;(void)v;en_calls++;return ESP_OK;}
void vTaskDelay(TickType_t t) {(void)t;}
static void check(int run,int vsense,int csrun,int cshold) {
 assert(tmc2209_set_current(run,400)==ESP_OK);
 assert(((registers[REG_CHOPCONF]>>17)&1)==(unsigned)vsense);
 assert(((registers[REG_IHOLD_IRUN]>>8)&31)==(unsigned)csrun);
 assert((registers[REG_IHOLD_IRUN]&31)==(unsigned)cshold);
 assert(en_calls==0);
}
int main(void) {
 assert(current_1500_experiment_run(800,400,.11f)==1500);
 assert(current_1500_experiment_run(800,300,.11f)==800);
 assert(current_1500_experiment_run(850,400,.11f)==850);
 assert(current_1500_experiment_run(800,400,.15f)==800);
 tmc2209_config_t c={.r_sense=.11f,.init_run_ma=1500,.init_hold_ma=400,.init_microstep=8};
 assert(tmc2209_init(&c)==ESP_OK);
 assert(!s_vsense && ((registers[REG_IHOLD_IRUN]>>8)&31)==26);
 assert((registers[REG_IHOLD_IRUN]&31)==6 && en_calls==0);
 check(800,1,25,12);check(850,1,27,12);check(1200,0,21,6);check(1500,0,26,6);
 assert(tmc2209_set_current(300,400)==ESP_ERR_INVALID_ARG);
 puts("shared VSENSE boot/set + 1500 conditional selection: OK");
}
