/* poleang 单元测试：通过类别契约替身区分单圈绝对角和相对累计位置。
 * 不连接硬件。预期值为手算角度，不调用生产换算函数作为 oracle。 */
#include <stdio.h>
#include "magnetic_encoder.h"
#include "poleang.h"
#include "params.h"

static uint32_t raw;
static int64_t position;
static int32_t velocity;
static int32_t resolution = 2097152;
static fw_params_t params;
static int failures, checks;
const fw_params_t *fw_params(void) { return &params; }
static int32_t cpr(magnetic_encoder_handle_t h) { (void)h; return resolution; }
static uint32_t angle(magnetic_encoder_handle_t h) { (void)h; return raw; }
static int64_t pos(magnetic_encoder_handle_t h) { (void)h; return position; }
static int32_t vel(magnetic_encoder_handle_t h) { (void)h; return velocity; }
static bool ok(magnetic_encoder_handle_t h) { (void)h; return true; }
static struct magnetic_encoder_s enc = {
    .counts_per_rev = cpr, .angle_counts = angle, .position_counts = pos,
    .velocity_counts_per_s = vel, .is_ok = ok,
};
#define CHECK(expr, expected) do { \
    int32_t actual = (expr), want = (expected); ++checks; \
    if (actual != want) { ++failures; \
        printf("FAIL line %d: %s = %d expected %d\n", __LINE__, #expr, actual, want); \
    } \
} while (0)

int main(void)
{
    poleang_init(&enc);
    /* 非零开机姿态，累计位移尚为0，不能当作绝对角零位。 */
    raw = 524288; position = 0;
    CHECK(poleang_theta_urad(), 1570796);
    raw = 1048576; position = 524288;
    CHECK(poleang_theta_urad(), 3141592);
    /* 同一机械零偏，启动姿态/累计整圈不影响已标定角。 */
    params.pole_zero_urad = 1570796;
    raw = 524288; position = 0;
    CHECK(poleang_theta_urad(), 0);
    raw = 1048576; position = 0; /* 在另一姿态重新初始化 */
    CHECK(poleang_theta_urad(), 1570796);
    position = 4LL * 2097152 + 123;
    CHECK(poleang_theta_urad(), 1570796);
    position = -4LL * 2097152 - 123;
    CHECK(poleang_theta_urad(), 1570796);
    params.pole_inv = 1;
    CHECK(poleang_theta_urad(), -1570796);
    /* 两个回绕边界和原生方向。 */
    params.pole_zero_urad = 0; params.pole_inv = 0;
    raw = 2097151;
    CHECK(poleang_theta_urad(), -3);
    raw = 0;
    CHECK(poleang_theta_urad(), 0);
    raw = 1048577;
    CHECK(poleang_theta_urad(), -3141590);
    raw = 1048576;
    CHECK(poleang_theta_urad(), 3141592);
    /* 任意类别分辨率，不依赖 MT6835 专有接口。 */
    resolution = 4096; raw = 1024; position = 0;
    CHECK(poleang_theta_urad(), 1570796);
    params.pole_zero_urad = -2000000; params.pole_inv = 1;
    CHECK(poleang_theta_urad(), 2712389);
    velocity = 4096;
    CHECK(poleang_vth_mrad_s(), -6283);
    params.pole_inv = 0;
    CHECK(poleang_vth_mrad_s(), 6283);
    printf("poleang: %d/%d passed\n", checks - failures, checks);
    return failures ? 1 : 0;
}
