/* MT6835读帧契约单元测试：只替代SPI，不连接设备。
 * 全零输入既可能是合法静止零角，也可能是线路恒低；没有独立健康
 * 证据时，两者必须得到同一“未确认”结果，不能将其当作断线证明。
 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "mt6835_hw.h"
#include "mt6835_urad.h"

static unsigned char frame[8];
static esp_err_t spi_result;
static int calls;
esp_err_t spi_bus_add_device(spi_host_device_t host,
    const spi_device_interface_config_t *cfg, spi_device_handle_t *out)
{
    (void)host; (void)cfg; *out = (void *)1; return ESP_OK;
}
esp_err_t spi_device_polling_transmit(spi_device_handle_t dev, spi_transaction_t *t)
{
    (void)dev;
    const unsigned char *tx = t->tx_buffer;
    assert(t->length == 48 && tx[0] == 0xa0 && tx[1] == 3);
    for (int i = 2; i < 6; ++i) assert(tx[i] == 0);
    memcpy(t->rx_buffer, frame, sizeof(frame));
    ++calls;
    return spi_result;
}
static void expect_rejected(mt6835_hw_handle_t h, mt6835_hw_fail_t expected)
{
    uint32_t raw = 123; uint8_t status = 123;
    assert(!mt6835_hw_read_raw(h, &raw, &status));
    assert(raw == 123 && status == 123);
    unsigned char saved[6]; mt6835_hw_fail_t kind;
    mt6835_hw_last_failure(h, &kind, saved);
    assert(kind == expected && !memcmp(saved, frame, sizeof(saved)));
}
static void expect_accepted(mt6835_hw_handle_t h, uint32_t expected, uint8_t s)
{
    uint32_t raw = 123; uint8_t status = 123;
    assert(mt6835_hw_read_raw(h, &raw, &status));
    assert(raw == expected && status == s);
}
int main(void)
{
    mt6835_hw_handle_t h;
    mt6835_hw_config_t cfg = {.host = 1, .clock_speed_hz = 1000000};
    assert(mt6835_hw_init(&cfg, &h) == ESP_OK);
    /* 独立已知CRC向量，不用被测CRC生成预期帧。 */
    unsigned char before_zero[8] = {0, 0, 0xff, 0xff, 0xf8, 0x1a};
    memcpy(frame, before_zero, sizeof(frame));
    expect_accepted(h, 2097151, 0);
    assert(mt6835_crc8(0, 0) == 0);
    memset(frame, 0, sizeof(frame));
    /* 已有健康历史亦不能区分随后静止零与持续全低，不能自动放行。 */
    for (int i = 0; i < 40; ++i) expect_rejected(h, MT6835_HW_FAIL_ALL_ZERO);
    /* 前16位为高阻，不得把其任意电平用作设备确认。 */
    frame[0] = frame[1] = 0xff;
    expect_rejected(h, MT6835_HW_FAIL_ALL_ZERO);
    unsigned char after_zero[8] = {0, 0, 0, 0, 8, 0x38};
    memcpy(frame, after_zero, sizeof(frame));
    expect_accepted(h, 1, 0);
    /* 零角带非零STATUS且CRC正确是不同输入，保持其现有有效语义。 */
    frame[4] = 1; frame[5] = 7;
    expect_accepted(h, 0, 1);
    frame[5] ^= 1;
    expect_rejected(h, MT6835_HW_FAIL_CRC);
    spi_result = (esp_err_t)-1;
    expect_rejected(h, MT6835_HW_FAIL_SPI_ERR);
    assert(calls == 46); /* 本次策略无重试、无新增寄存器操作。 */
    puts("MT6835 frame checks passed; zero-angle ambiguity remains rejected");
}
