#pragma once
#include <stdint.h>
#include <stdbool.h>
/* Reply is addressed to master 0xff, not the slave address in the request. */
static inline bool tmc2209_response_matches(const uint8_t *b, uint8_t reg, uint8_t crc)
{
    return b && b[0] == 0x05 && b[1] == 0xff && b[2] == (reg & 0x7f)
        && b[7] == crc;
}
