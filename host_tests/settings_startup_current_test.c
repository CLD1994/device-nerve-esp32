/* 启动电流覆盖单元测试：隔离 settings 持久化 API，不连接 NVS 或硬件。 */
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "settings_startup_current.h"
static int run_ma, hold_ma, reads, validates, writes, last_idx;
static float last_value;
static settings_status_t store_result;
int settings_run_current_ma(void) {++reads;return run_ma;}
int settings_hold_current_ma(void) {++reads;return hold_ma;}
bool settings_is_valid(int idx,float value) {
    ++validates;
    return idx==SET_RUN_MA && isfinite(value) && value>=1 && value<=2000 &&
           value==(int)value && value>=hold_ma;
}
settings_status_t settings_set(int idx,float value) {
    ++writes;last_idx=idx;last_value=value;
    if(store_result==SETTINGS_OK)run_ma=(int)value;
    return store_result;
}
static void reset(int run,int hold) {
    run_ma=run;hold_ma=hold;reads=validates=writes=0;last_idx=-1;
    last_value=0;store_result=SETTINGS_OK;
}
int main(void) {
    reset(1500,400);
    assert(settings_apply_startup_run_current(false,1000)==SETTINGS_OK);
    assert(reads==0 && validates==0 && writes==0 && run_ma==1500 && hold_ma==400);
    reset(1000,400);
    assert(settings_apply_startup_run_current(true,1000)==SETTINGS_OK);
    assert(writes==0 && run_ma==1000 && hold_ma==400);
    reset(1500,400);
    assert(settings_apply_startup_run_current(true,1000)==SETTINGS_OK);
    assert(writes==1 && last_idx==SET_RUN_MA && last_value==1000);
    assert(run_ma==1000 && hold_ma==400);
    reset(1500,1200);
    assert(settings_apply_startup_run_current(true,1000)==SETTINGS_INVALID);
    assert(writes==0 && run_ma==1500 && hold_ma==1200);
    reset(1500,400);store_result=SETTINGS_STORAGE;
    assert(settings_apply_startup_run_current(true,1000)==SETTINGS_STORAGE);
    assert(writes==1 && run_ma==1500 && hold_ma==400);
    reset(1500,400);store_result=SETTINGS_INVALID;
    assert(settings_apply_startup_run_current(true,1000)==SETTINGS_INVALID);
    assert(writes==1 && hold_ma==400);
    for(int target=0;target<=2001;target+=2001) {
        reset(1500,0);
        assert(settings_apply_startup_run_current(true,target)==SETTINGS_INVALID);
        assert(writes==0);
    }
    reset(1500,1000);
    assert(settings_apply_startup_run_current(true,1000)==SETTINGS_OK);
    assert(hold_ma==1000);
    /* 连续启动和关闭选项均不撤回已经保存的请求。 */
    reset(1500,400);
    assert(settings_apply_startup_run_current(true,1000)==SETTINGS_OK);
    assert(settings_apply_startup_run_current(true,1000)==SETTINGS_OK);
    assert(settings_apply_startup_run_current(false,1500)==SETTINGS_OK);
    assert(writes==1 && run_ma==1000 && hold_ma==400);
    /* 域上下边界与较大负数，不把非法值转成有效请求。 */
    reset(1500,0);
    assert(settings_apply_startup_run_current(true,1)==SETTINGS_OK);
    assert(run_ma==1);
    assert(settings_apply_startup_run_current(true,2000)==SETTINGS_OK);
    assert(run_ma==2000);
    assert(settings_apply_startup_run_current(true,-1)==SETTINGS_INVALID);
    assert(writes==2);
    puts("settings startup current: PASS");
    return 0;
}
