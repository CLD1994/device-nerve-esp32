#include <assert.h>
#include <string.h>
#include <stdint.h>
#include <stdio.h>
#include "telemetry.h"
int main(void){
 char b[80];telemetry_lane_t c={true,100,INT32_MIN,INT32_MIN},p={true,100,-3141592,INT32_MIN};
 const char *expected="STATE 3 -2147483648 -3141592 -2147483648 -2147483648\n";
 int n=telemetry_format_state(b,sizeof(b),100,c,p);
 assert(n==(int)strlen(expected));assert(!strcmp(b,expected));
 assert(telemetry_format_state(b,(size_t)n,100,c,p)<0);
 assert(telemetry_format_state(b,(size_t)n+1,100,c,p)==n);
 assert(telemetry_format_state(NULL,sizeof(b),100,c,p)<0);
 assert(telemetry_format_state(b,sizeof(b),-1,c,p)<0);
 puts("decimal six-token state passed");
}
