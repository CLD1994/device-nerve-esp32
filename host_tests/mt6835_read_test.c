/* 真实采样实现+SPI替身：完整003..006、同任务B/S分组、取消和恢复burst。 */
#include <assert.h>
#include <string.h>
#include "../components/magnetic_encoder/magnetic_encoder_mt6835.c"
static int64_t clock_us=100;
static unsigned burst_reads,single_reads,next_register=3;
static bool bad_crc;
int64_t esp_timer_get_time(void) { return clock_us; }
esp_err_t spi_bus_add_device(spi_host_device_t h,const spi_device_interface_config_t*c,spi_device_handle_t*d)
{ (void)h; (void)c; *d=(void*)1; return ESP_OK; }
esp_err_t spi_device_polling_transmit(spi_device_handle_t h,spi_transaction_t*t)
{
    (void)h;
    const uint8_t *tx=t->tx_buffer; uint8_t *rx=t->rx_buffer;
    uint8_t bytes[4]={1,2,7,mt6835_crc8(8256,7)};
    if (bad_crc) bytes[3]^=1;
    if(t->length==48) {
        assert(tx[0]==0xa0&&tx[1]==3); memcpy(rx+2,bytes,4); burst_reads++;
    } else {
        assert(t->length==24&&tx[0]==0x30&&tx[1]==next_register);
        rx[2]=bytes[next_register-3]; next_register=next_register==6 ? 3 : next_register+1;
        single_reads++;
    }
    clock_us+=25;
    return ESP_OK;
}
int main(void)
{
    static me_mt6835_inst_t me;
    mt6835_hw_config_t cfg={.host=1};
    assert(mt6835_hw_init(&cfg,&me.hw)==ESP_OK);
    magnetic_encoder_handle_t e=(magnetic_encoder_handle_t)&me;
    uint32_t raw=0;uint8_t status=0,frame[6];
    assert(diagnostic_read(&me,&raw,&status)&&raw==8256&&status==7);
    assert(read_test_start(e)&&!read_test_start(e));
    for (unsigned i=0;i<=8000;++i) {
        clock_us=1000000+(int64_t)i*500;
        assert(diagnostic_read(&me,&raw,&status));
    }
    magnetic_encoder_read_test_state_t state;
    read_test_state(e,&state);assert(state.done&&!state.busy&&!state.canceled);
    assert(state.count==800&&single_reads==16000&&next_register==3);
    for(unsigned i=0;i<state.count;++i) {
        magnetic_encoder_read_test_row_t r;
        assert(read_test_row(e,i,&r));
        assert(r.phase==i/200&&r.first_in_phase==(i%200==0));
        assert(r.valid&&r.crc==r.crc_expected&&r.raw_counts==8256&&r.status==7);
        assert(r.end_us-r.begin_us==(r.phase%2 ? 100 : 25));
    }
    assert(!me.read_was_single&&copy_success_frame(&me,frame));
    assert(read_test_start(e)); clock_us+=1000;diagnostic_read(&me,&raw,&status);
    clock_us+=1000000;bad_crc=true;
    assert(!diagnostic_read(&me,&raw,&status));
    assert(!copy_success_frame(&me,frame)); /* 不能把上次burst原帧冒充S */
    read_test_cancel(e);read_test_state(e,&state);assert(state.busy);
    bad_crc=false;clock_us+=500;assert(diagnostic_read(&me,&raw,&status));
    read_test_state(e,&state);assert(!state.busy&&state.canceled);
    assert(!me.read_was_single&&copy_success_frame(&me,frame));
    puts("MT6835 B/S same-task checks passed");
}
