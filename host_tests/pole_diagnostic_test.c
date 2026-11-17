#include <assert.h>
#include "magnetic_encoder_diagnostic.h"
int main(void) {
    me_diag_t d = {0};
    me_diag_point_t p = {.valid=0};
    me_diag_observe(&d, p); assert(!d.captured);
    p.valid=1; p.seq=11; me_diag_observe(&d,p);
    p.valid=0; p.reason=2; me_diag_observe(&d,p);
    assert(d.captured && d.before.seq==11 && d.after.reason==2);
    p.reason=4; me_diag_observe(&d,p); assert(d.after.reason==2);
    p.valid=1; me_diag_observe(&d,p); p.valid=0; me_diag_observe(&d,p);
    assert(d.transitions==2);
    me_diag_arm(&d,7); assert(!d.captured && d.run_id==7 && !d.previous.valid);
    for(int i=0;i<9;i++) me_diag_enqueue(&d,(me_diag_log_t){.kind=1,.value=i});
    assert(d.dropped==1);
    me_diag_log_t log; for(int i=0;i<8;i++){assert(me_diag_pop(&d,&log));assert(log.value==i);}
    assert(!me_diag_pop(&d,&log));
    d.count=8;d.dropped=UINT64_MAX;me_diag_enqueue(&d,(me_diag_log_t){0});assert(d.dropped==UINT64_MAX);
    d.transitions=UINT64_MAX;d.previous.valid=true;p.valid=false;me_diag_observe(&d,p);assert(d.transitions==UINT64_MAX);
    return 0;
}
