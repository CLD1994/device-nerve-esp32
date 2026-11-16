#include <assert.h>
#include <string.h>
#include <stdint.h>
#include <stdio.h>
#include "telemetry.h"
int main(void){
 char b[83];telemetry_lane_t c={true,100,1,1,2},p={true,100,2,3,4};
 assert(telemetry_format_state(b,83,UINT32_MAX,20100,c,p)==82);
 assert(strstr(b," 3 0001 0002 4e20 4e20 "));
 assert(telemetry_format_state(b,83,1,20101,c,p)==82);
 assert(strstr(b," 0 0000 0000 ffff ffff 00000000 00000000 00000000 00000000\n"));
 p.valid=false; assert(telemetry_format_state(b,83,1,100,c,p)==82);
 assert(strstr(b," 1 0001 0000 0000 ffff 00000001 00000000 00000002 00000000\n"));
 c.valid=false;p.valid=true;assert(telemetry_format_state(b,83,1,100,c,p)==82);
 assert(strstr(b," 2 0000 0002 ffff 0000 00000000 00000003 00000000 00000004\n"));
 c.valid=true;c.sampled_at_us=101;p.sampled_at_us=-1;
 assert(telemetry_format_state(b,83,1,100,c,p)==82);assert(strstr(b," 0 0000 0000 ffff ffff "));
 c.sampled_at_us=INT64_C(0x100000000);c.sample_seq=65536;
 assert(telemetry_format_state(b,83,0,INT64_C(0x100000000),c,p)==82);
 assert(strstr(b,"STATE 00000000 00000000 1 0000 0000 0000 ffff "));
 c=(telemetry_lane_t){true,100,1,INT32_MAX,INT32_MIN};
 for(int sign=-1;sign<=1;sign+=2){
  p=(telemetry_lane_t){true,100,2,sign*3141592,INT32_MIN};
  assert(telemetry_format_state(b,83,1,100,c,p)==82);assert(strstr(b," 3 0001 0002 "));
  p.position=sign*3141593;
  assert(telemetry_format_state(b,83,1,100,c,p)==82);
  assert(strstr(b," 1 0001 0000 0000 ffff 7fffffff 00000000 80000000 00000000\n"));
 }
 puts("independent lane validity passed");
}
