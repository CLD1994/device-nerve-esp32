#include <assert.h>
#include <stdio.h>
#include "../components/cartfsm/cartfsm_following_error.h"
static int tick(cartfsm_following_error_t *s,uint32_t run,int64_t now,int64_t e) {
 return cartfsm_following_error_update(s,run,now,e,3000,50000,50000,1000,2);
}
int main(void) {
 cartfsm_following_error_t s={0};
 assert(tick(&s,1,0,4000)==0); /* stable offsets are tolerated */
 assert(tick(&s,1,50000,4000)==0);
 assert(tick(&s,1,100000,5000)==0);
 assert(tick(&s,1,150000,6000)==2); /* two outward windows */
 assert(tick(&s,2,200000,-4000)==0); /* run resets history */
 assert(tick(&s,2,250000,-5000)==0);
 assert(tick(&s,2,300000,-6000)==2);
 assert(tick(&s,3,350000,49999)==0);
 assert(tick(&s,3,350001,50000)==1); /* exact hard limit */
 assert(tick(&s,4,0,4000)==0);
 assert(tick(&s,4,100000,5000)==0); /* rate too small in delayed 100ms window */
 assert(s.growing_windows==0);
 assert(tick(&s,4,150000,6000)==0);
 assert(tick(&s,4,200000,5000)==0); /* decreasing resets */
 assert(s.growing_windows==0);
 assert(tick(&s,4,100,5000)==0); /* backwards clock resets */
 assert(s.growing_windows==0);
 puts("following error boundaries/run/time checks passed");
}
