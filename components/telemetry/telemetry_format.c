#include "telemetry.h"
#include <stdio.h>
#include <inttypes.h>
static bool lane_valid(telemetry_lane_t p,int64_t now)
{
 return p.valid && p.sampled_at_us>=0 && p.sampled_at_us<=now && now-p.sampled_at_us<=20000;
}
int telemetry_format_state(char *buf,size_t len,int64_t now,
                           telemetry_lane_t cart,telemetry_lane_t pole)
{
 if(!buf || len==0 || now<0) return -1;
 bool c=lane_valid(cart,now),p=lane_valid(pole,now)
     && pole.position>=-3141592 && pole.position<=3141592;
 int n=snprintf(buf,len,
  "STATE %u %" PRId32 " %" PRId32 " %" PRId32 " %" PRId32 "\n",
  (unsigned)(c|(p<<1)),
  c?cart.position:INT32_C(0),p?pole.position:INT32_C(0),
  c?cart.velocity:INT32_C(0),p?pole.velocity:INT32_C(0));
 return n>0 && (size_t)n<len ? n : -1;
}
