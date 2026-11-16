"""统一 STATE 固定宽度帧；无效通道不产生测量值。"""
import re

_HEX = r'[0-9a-fA-F]'
_PATTERN = re.compile('STATE ' + ' '.join(_HEX+'{'+str(n)+'}' for n in (8,8,1,4,4,4,4,8,8,8,8)))


def parse_state_frame(line):
    """输入不含行结束符。非 STATE 返回 None，本标签畸形抛 ValueError。"""
    tokens = line.split()
    if not tokens or tokens[0] != 'STATE':
        return None
    if len(line) != 81 or not _PATTERN.fullmatch(line):
        raise ValueError('STATE 固定宽度或十六进制字段错误')
    boot,tick,flags,cs,ps,ca,pa,x,theta,vx,vth = (int(v,16) for v in tokens[1:])
    if flags > 3:
        raise ValueError('STATE 通道标志越界')

    def signed(v):
        return v if v < 2**31 else v-2**32

    def lane(valid, seq, age, first, second, names):
        if not valid:
            if seq != 0 or age != 0xffff or first != 0 or second != 0:
                raise ValueError('STATE 无效通道哨兵错误')
            return None
        if age > 20000:
            raise ValueError('STATE 有效通道样本过旧')
        return dict(seq=seq, age_us=age, **{names[0]:signed(first),names[1]:signed(second)})

    cart=lane(flags & 1,cs,ca,x,vx,('x_um','vx_mm_s'))
    pole=lane(flags & 2,ps,pa,theta,vth,('theta_urad','vth_mrad_s'))
    if pole is not None and abs(pole['theta_urad']) > 3141592:
        raise ValueError('STATE 摆角越界')
    return dict(boot=boot,tick=tick,flags=flags,cart=cart,pole=pole)
