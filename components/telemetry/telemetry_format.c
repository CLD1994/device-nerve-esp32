#include "telemetry.h"
#include <stdio.h>
#include <inttypes.h>
static bool lane_valid(telemetry_lane_t p,int64_t now)
{
 return p.valid && p.sampled_at_us>=0 && p.sampled_at_us<=now && now-p.sampled_at_us<=20000;
}
int telemetry_format_state(char *buf,size_t len,uint32_t boot,int64_t now,
                           telemetry_lane_t cart,telemetry_lane_t pole)
{
 if(!buf || len<83 || now<0) return -1;
 bool c=lane_valid(cart,now),p=lane_valid(pole,now)
     && pole.position>=-3141592 && pole.position<=3141592;
 int n=snprintf(buf,len,
  "STATE %08" PRIx32 " %08" PRIx32 " %x %04x %04x %04x %04x %08" PRIx32 " %08" PRIx32 " %08" PRIx32 " %08" PRIx32 "\n",
  boot,(uint32_t)now,(unsigned)(c|(p<<1)),
  c?(unsigned)(cart.sample_seq&0xffff):0,p?(unsigned)(pole.sample_seq&0xffff):0,
  c?(unsigned)(now-cart.sampled_at_us):0xffff,p?(unsigned)(now-pole.sampled_at_us):0xffff,
  c?(uint32_t)cart.position:UINT32_C(0),p?(uint32_t)pole.position:UINT32_C(0),
  c?(uint32_t)cart.velocity:UINT32_C(0),p?(uint32_t)pole.velocity:UINT32_C(0));
 return n==82 && (size_t)n<len ? n : -1;
}
