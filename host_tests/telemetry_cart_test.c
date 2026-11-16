#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include "telemetry.h"
int main(void){
 telemetry_cart_gate_t gate={0};char b[128];
#ifndef CONFIG_TELEMETRY_CART_DIAGNOSTICS
 strcpy(b,"unchanged");
 assert(telemetry_format_cart(b,sizeof(b),&gate,0,true,0,1,1,2)==0);
 assert(!strcmp(b,"unchanged"));
 assert(!gate.initialized);
#else
 assert(telemetry_format_cart(b,sizeof(b),&gate,100,true,99,1,-42,600)>0);
 assert(!strcmp(b,"CART_STATE1 100 99 1 1 -42 600\n"));
 assert(telemetry_format_cart(b,sizeof(b),&gate,101,false,-1,0,123,456)==0);
 assert(telemetry_format_cart(b,sizeof(b),&gate,20099,true,99,1,1,2)==0);
 assert(telemetry_format_cart(b,sizeof(b),&gate,20100,false,-1,0,123,456)>0);
 assert(!strcmp(b,"CART_STATE1 20100 0\n"));
 assert(telemetry_format_cart(b,sizeof(b),&gate,20101,true,20100,2,1,2)==0);
 assert(telemetry_format_cart(b,sizeof(b),&gate,10,true,9,3,1,2)==0);
 assert(telemetry_format_cart(b,sizeof(b),&gate,20009,true,9,3,1,2)==0);
 assert(telemetry_format_cart(b,sizeof(b),&gate,20010,true,9,3,1,2)>0);
 gate=(telemetry_cart_gate_t){0};
 for(int i=0;i<1000;i++){
  int n=telemetry_format_cart(b,sizeof(b),&gate,i*1000,i%2,i*1000,1,1,2);
  assert((n>0)==(i%20==0));
 }
 gate=(telemetry_cart_gate_t){0};
 assert(telemetry_format_cart(b,sizeof(b),&gate,-1,false,0,0,0,0)<0 && !gate.initialized);
 assert(telemetry_format_cart(b,sizeof(b),&gate,10,true,11,1,0,0)<0 && !gate.initialized);
 assert(telemetry_format_cart(b,sizeof(b),&gate,10,true,9,0,0,0)<0 && !gate.initialized);
 assert(telemetry_format_cart(b,2,&gate,10,true,9,1,0,0)<0 && !gate.initialized);
 assert(telemetry_format_cart(b,sizeof(b),&gate,10,true,9,1,0,0)>0);
 assert(!strcmp(b,"CART_STATE1 10 9 1 1 0 0\n"));
 gate=(telemetry_cart_gate_t){0};
 int n=telemetry_format_cart(b,sizeof(b),&gate,INT64_MAX,true,INT64_MAX,UINT64_MAX,INT32_MIN,INT32_MIN);
 assert(n==99 && strlen(b)==99);
 assert(strstr(b,"18446744073709551615"));
#endif
 puts("cart telemetry formatter passed");
}
