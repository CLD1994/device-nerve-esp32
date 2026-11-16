#include <assert.h>
#include <string.h>
#include <stdint.h>
#include <stdio.h>
#include "telemetry.h"
int main(void){
 char b[83];telemetry_lane_t c={true,100,65536,-1,INT32_MIN},p={true,100,65535,3141592,0};
 assert(telemetry_format_state(b,sizeof(b),0,100,c,p)==82);
 assert(!strcmp(b,"STATE 00000000 00000064 3 0000 ffff 0000 0000 ffffffff 002fefd8 80000000 00000000\n"));
 assert(strlen(b)==82); /* fixed-width including LF */
 assert(telemetry_format_state(b,82,0,100,c,p)<0);
 assert(telemetry_format_state(NULL,83,0,100,c,p)<0);
 assert(telemetry_format_state(b,83,0,-1,c,p)<0);
 puts("fixed hex state passed");
}
