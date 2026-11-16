#include <assert.h>
#include <string.h>
#include <stdint.h>
#include <stdio.h>
#include "telemetry.h"
int main(void){
 char b[80];telemetry_lane_t c={true,100,1,2},p={true,100,3,4};
 assert(telemetry_format_state(b,sizeof(b),20100,c,p)>0); assert(!strcmp(b,"STATE 3 1 3 2 4\n"));

 assert(telemetry_format_state(b,sizeof(b),20101,c,p)>0); assert(!strcmp(b,"STATE 0 0 0 0 0\n"));

 p.valid=false; assert(telemetry_format_state(b,sizeof(b),100,c,p)>0); assert(!strcmp(b,"STATE 1 1 0 2 0\n"));

 c.valid=false;p.valid=true;assert(telemetry_format_state(b,sizeof(b),100,c,p)>0); assert(!strcmp(b,"STATE 2 0 3 0 4\n"));

 c.valid=true;c.sampled_at_us=101;p.sampled_at_us=-1;
 assert(telemetry_format_state(b,sizeof(b),100,c,p)>0); assert(!strcmp(b,"STATE 0 0 0 0 0\n"));
 c.sampled_at_us=INT64_C(0x100000000);
 assert(telemetry_format_state(b,sizeof(b),INT64_C(0x100000000),c,p)>0); assert(!strcmp(b,"STATE 1 1 0 2 0\n"));

 c=(telemetry_lane_t){true,100,INT32_MAX,INT32_MIN};
 for(int sign=-1;sign<=1;sign+=2){
  p=(telemetry_lane_t){true,100,sign*3141592,INT32_MIN};
  assert(telemetry_format_state(b,sizeof(b),100,c,p)>0);
  assert(!strncmp(b,"STATE 3 ",8));
  p.position=sign*3141593;
  assert(telemetry_format_state(b,sizeof(b),100,c,p)>0); assert(!strcmp(b,"STATE 1 2147483647 0 -2147483648 0\n"));

 }
 puts("independent lane validity passed");
}
