#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "telemetry.h"
int main(void) {
    telemetry_validity_t gate={0}; char buf[128];
    assert(telemetry_format_measurement(buf,sizeof(buf),&gate,0,false,false,1,2,3,4)>0);
    assert(strcmp(buf,"VEL_VALID 0 0\n")==0);
    assert(telemetry_format_measurement(buf,sizeof(buf),&gate,99999,false,false,1,2,3,4)==0);
    assert(telemetry_format_measurement(buf,sizeof(buf),&gate,100000,false,false,1,2,3,4)>0);
    assert(strcmp(buf,"VEL_VALID 0 0\n")==0);
    assert(telemetry_format_measurement(buf,sizeof(buf),&gate,100001,true,false,1,2,3,4)>0);
    assert(strcmp(buf,"VEL_VALID 1 0\n")==0);
    assert(telemetry_format_measurement(buf,sizeof(buf),&gate,100002,true,true,1,2,3,4)>0);
    assert(strcmp(buf,"VEL_VALID 1 1\nSTATE 1 2 3 4\n")==0);
    assert(telemetry_format_measurement(buf,sizeof(buf),&gate,102002,true,true,5,6,7,8)>0);
    assert(strcmp(buf,"STATE 5 6 7 8\n")==0);
    assert(telemetry_format_measurement(buf,sizeof(buf),&gate,102003,false,true,5,6,0,8)>0);
    assert(strcmp(buf,"VEL_VALID 0 1\n")==0);
    assert(telemetry_format_measurement(buf,sizeof(buf),&gate,102004,true,true,1,2,3,4)>0);
    assert(telemetry_format_measurement(buf,sizeof(buf),&gate,202004,true,true,1,2,3,4)>0);
    assert(strcmp(buf,"VEL_VALID 1 1\nSTATE 1 2 3 4\n")==0);
    telemetry_validity_t old=gate;
    assert(telemetry_format_measurement(buf,1,&gate,102004,true,true,1,2,3,4)<0);
    assert(memcmp(&old,&gate,sizeof(gate))==0);
    puts("telemetry validity passed");
}
