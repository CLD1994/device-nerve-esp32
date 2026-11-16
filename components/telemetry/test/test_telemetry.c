/* 目标测试验证十进制组帧；物理串口吞吐需独立现场验证。 */
#include "telemetry.h"
#include <string.h>
#include "unity.h"
TEST_CASE("十进制双路STATE", "[telemetry]")
{
 char b[80];telemetry_lane_t c={true,100,-1,0},p={false,0,99,99};
 const char *expected="STATE 1 -1 0 0 0\n";
 TEST_ASSERT_EQUAL_INT(strlen(expected),telemetry_format_state(b,sizeof(b),100,c,p));
 TEST_ASSERT_EQUAL_STRING(expected,b);
 TEST_ASSERT_TRUE(telemetry_format_state(b,strlen(expected),100,c,p)<0);
}
