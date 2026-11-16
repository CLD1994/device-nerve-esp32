"""严格十进制 STATE：仅测量与有效位，不提供设备身份或采样时刻。"""
import re

_PATTERN = re.compile(r'STATE ([0-3]) ((?:0|-?[1-9][0-9]{0,9})) ((?:0|-?[1-9][0-9]{0,9})) ((?:0|-?[1-9][0-9]{0,9})) ((?:0|-?[1-9][0-9]{0,9}))')


def parse_state_frame(line):
    """不含行结束符；非 STATE 返回 None，本标签畸形抛 ValueError。"""
    tokens=line.split()
    if not tokens or tokens[0]!='STATE':return None
    match=_PATTERN.fullmatch(line)
    if match is None or len(line)>52:
        raise ValueError('STATE 十进制字段或格式错误')
    flags,x,theta,vx,vth=map(int,match.groups())
    if any(not -2147483648<=v<=2147483647 for v in (x,theta,vx,vth)):
        raise ValueError('STATE 测量越界')
    if not flags&1 and (x!=0 or vx!=0):raise ValueError('STATE 无效小车通道必须为零')
    if not flags&2 and (theta!=0 or vth!=0):raise ValueError('STATE 无效摆杆通道必须为零')
    if flags&2 and abs(theta)>3141592:raise ValueError('STATE 摆角越界')
    return dict(flags=flags,
        cart=dict(x_um=x,vx_mm_s=vx) if flags&1 else None,
        pole=dict(theta_urad=theta,vth_mrad_s=vth) if flags&2 else None)
