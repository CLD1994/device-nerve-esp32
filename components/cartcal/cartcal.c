#include "cartcal.h"
#include "params.h"
#include "settings.h"
#include "nvs.h"
#include <string.h>
#include <math.h>
#include <limits.h>
#include <float.h>

/* 固定小端格式：magic/version/L/zero/inv/mm_per_rev(IEEE754)/CRC32。
 * 不直接保存 C 结构体，避免 ABI 填充与 long 位宽影响记录格式。 */
#define RECORD_SIZE 28
#define RECORD_MAGIC UINT32_C(0x43414c31)
#define RECORD_VERSION UINT32_C(1)
_Static_assert(sizeof(float) == 4 && FLT_RADIX == 2 && FLT_MANT_DIG == 24
               && FLT_MAX_EXP == 128, "IEEE754 binary32 float required");

static void put32(uint8_t *p, uint32_t v)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (i * 8));
}
static uint32_t get32(const uint8_t *p)
{
    uint32_t v = 0;
    for (unsigned i = 0; i < 4; ++i) v |= (uint32_t)p[i] << (i * 8);
    return v;
}
static uint32_t crc32(const uint8_t *p, size_t n)
{
    uint32_t crc = UINT32_MAX;
    while (n--) {
        crc ^= *p++;
        for (unsigned i = 0; i < 8; ++i)
            crc = (crc >> 1) ^ (UINT32_C(0xedb88320) & (0u - (crc & 1u)));
    }
    return ~crc;
}
static bool valid(const cartcal_record_t *r)
{
    return (r->length_um == 0 || fw_calib_length_valid(r->length_um))
        && fw_params_valid(FP_POLE_ZERO_URAD, r->pole_zero_urad)
        && fw_params_valid(FP_POLE_INV, r->pole_inv)
        /* settings 的通用校验器先转 int；先排除损坏的浮点位模式。 */
        && isfinite(r->mm_per_rev)
        && (double)r->mm_per_rev >= INT_MIN
        && (double)r->mm_per_rev <= INT_MAX
        && settings_is_valid(SET_MM_PER_REV, r->mm_per_rev);
}

esp_err_t cartcal_save(const cartcal_record_t *r)
{
    if (!r) return ESP_ERR_INVALID_ARG;
    if (!valid(r)) return ESP_ERR_INVALID_STATE;
    uint8_t blob[RECORD_SIZE];
    uint32_t scale;
    memcpy(&scale, &r->mm_per_rev, sizeof(scale));
    put32(blob, RECORD_MAGIC);
    put32(blob + 4, RECORD_VERSION);
    put32(blob + 8, (uint32_t)r->length_um);
    put32(blob + 12, (uint32_t)r->pole_zero_urad);
    put32(blob + 16, (uint32_t)r->pole_inv);
    put32(blob + 20, scale);
    put32(blob + 24, crc32(blob, 24));
    nvs_handle_t handle;
    esp_err_t err = nvs_open("cartcal", NVS_READWRITE, &handle);
    if (err != ESP_OK) return err;
    err = nvs_set_blob(handle, "record", blob, sizeof(blob));
    if (err == ESP_OK) err = nvs_commit(handle);
    nvs_close(handle);
    return err;
}

esp_err_t cartcal_load(cartcal_record_t *out)
{
    if (!out) return ESP_ERR_INVALID_ARG;
    nvs_handle_t handle;
    esp_err_t err = nvs_open("cartcal", NVS_READONLY, &handle);
    if (err != ESP_OK) return err;
    size_t n = 0;
    err = nvs_get_blob(handle, "record", NULL, &n);
    uint8_t blob[RECORD_SIZE];
    if (err == ESP_OK) {
        if (n != sizeof(blob)) err = ESP_ERR_INVALID_STATE;
        else err = nvs_get_blob(handle, "record", blob, &n);
    }
    nvs_close(handle);
    if (err != ESP_OK) return err;
    if (n != sizeof(blob) || get32(blob) != RECORD_MAGIC
        || get32(blob + 4) != RECORD_VERSION
        || get32(blob + 24) != crc32(blob, 24)) return ESP_ERR_INVALID_STATE;
    cartcal_record_t r = {
        .length_um = (int32_t)get32(blob + 8),
        .pole_zero_urad = (int32_t)get32(blob + 12),
        .pole_inv = (int32_t)get32(blob + 16),
    };
    uint32_t scale = get32(blob + 20);
    memcpy(&r.mm_per_rev, &scale, sizeof(scale));
    if (!valid(&r)) return ESP_ERR_INVALID_STATE;
    *out = r;
    return ESP_OK;
}
