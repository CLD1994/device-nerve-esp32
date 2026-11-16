"""测试专用线协议编码；不导入生产解析器或有效性规则。"""
def state_line(x=0, theta=0, vx=0, vth=0, *, boot=1, tick=1, seq=1, flags=3, cart_age=0, pole_age=0):
    cart=bool(flags&1);pole=bool(flags&2)
    return ('STATE %08x %08x %x %04x %04x %04x %04x %08x %08x %08x %08x\n' % (
        boot,tick,flags,seq if cart else 0,seq if pole else 0,
        cart_age if cart else 65535,pole_age if pole else 65535,
        int(x)&0xffffffff if cart else 0,int(theta)&0xffffffff if pole else 0,
        int(vx)&0xffffffff if cart else 0,int(vth)&0xffffffff if pole else 0)).encode('ascii')
