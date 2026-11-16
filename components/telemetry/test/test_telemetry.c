/* 目标测试验证固定宽度组帧；物理串口吞吐需独立现场验证。 */
#include "telemetry.h"
#include <string.h>
#include "unity.h"
TEST_CASE("固定宽度双路STATE", "[telemetry]")
{
 char b[83];
 telemetry_lane_t c={true,100,65536,-1,0},p={false,0,0,99,99};
 TEST_ASSERT_EQUAL_INT(82,telemetry_format_state(b,sizeof(b),0,100,c,p));
 TEST_ASSERT_EQUAL_STRING("STATE 00000000 00000064 1 0000 0000 0000 ffff ffffffff 00000000 00000000 00000000\n",b);
 TEST_ASSERT_EQUAL_INT(82,strlen(b));
 TEST_ASSERT_TRUE(telemetry_format_state(b,82,0,100,c,p)<0);
}
