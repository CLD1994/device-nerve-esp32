"""独立测试线协议生成器；不导入生产解析器。"""
def state_line(x=0,theta=0,vx=0,vth=0,*,flags=3):
    return ('STATE %d %d %d %d %d\n'%(flags,x if flags&1 else 0,
        theta if flags&2 else 0,vx if flags&1 else 0,vth if flags&2 else 0)).encode('ascii')
