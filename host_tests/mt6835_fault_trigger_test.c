#include "cartfsm_fixture.h"
#include "driver/gpio.h"
static unsigned highs,lows,configs;
static bool init_fail;
esp_err_t gpio_set_level(int pin,int level){assert(pin==CONFIG_CARTFSM_MT6835_FAULT_TRIGGER_GPIO);if(level){assert(halt_calls>0);assert(cartfsm_mode()==CM_FAULT);highs++;}else lows++;return ESP_OK;}
esp_err_t gpio_config(const gpio_config_t *p){assert(p->pin_bit_mask==(UINT64_C(1)<<CONFIG_CARTFSM_MT6835_FAULT_TRIGGER_GPIO));configs++;return init_fail ? ESP_FAIL : ESP_OK;}
static void ready(void){cmd(CART_CMD_CONFIRM_LEFT);cmd(CART_CMD_ENABLE);assert(cartfsm_mode()==CM_READY);}
int main(int argc,char **argv){
 assert(argc==2);disk=(cartcal_record_t){.length_um=850000,.mm_per_rev=40};load_error=ESP_OK;
 if(!strcmp(argv[1],"init-fail")){init_fail=true;assert(cartfsm_start()!=ESP_OK);assert(!highs);return 0;}
 boot();assert(lows==1 && configs==1 && highs==0);
 pole_healthy=false;supervise_once();assert(!highs); /* DISABLED does not accept fault */
 pole_healthy=true;ready();
 if(!strcmp(argv[1],"cart")){healthy=false;supervise_once();assert(cartfsm_mode()==CM_FAULT && !highs);pole_healthy=false;supervise_once();assert(!highs);return 0;}
 if(!strcmp(argv[1],"power")){power_ready=false;pole_healthy=false;supervise_once();assert(cartfsm_mode()==CM_FAULT && !highs);return 0;}
 pole_healthy=false;supervise_once();assert(cartfsm_mode()==CM_FAULT && highs==1);
 supervise_once();assert(highs==1);pole_healthy=true;cmd(CART_CMD_RESET);assert(cartfsm_mode()==CM_DISABLED && highs==1);
 ready();pole_healthy=false;supervise_once();assert(highs==1);assert(lows==1);
 puts("accepted MT6835 fault triggers once after protective stop");
}
