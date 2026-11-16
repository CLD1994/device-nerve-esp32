"""独立小车观测帧；不替代完整 STATE 或改变运动门禁。"""
import re


def parse_cart_state(line):
    """合法 CART_STATE1 返回字段；其他标签返回 None；畸形本标签抛 ValueError。

    输入为去掉串口行结束符的文本。无效帧保留设备时间，不虚构测量值。
    """
    parts = line.split()
    if not parts or parts[0] != 'CART_STATE1':
        return None
    if len(line) > 159 or not line.isascii():
        raise ValueError('CART_STATE1 行长或字符非法')
    if len(parts) not in (3, 7):
        raise ValueError('CART_STATE1 字段数量错误')

    def number(token, low, high):
        if not re.fullmatch(r'-?[0-9]{1,20}', token):
            raise ValueError('CART_STATE1 数字字段非法')
        value = int(token)
        if not low <= value <= high:
            raise ValueError('CART_STATE1 数字字段越界')
        return value

    device = number(parts[1], 0, 2**63-1)
    result = dict(device_us=device, sample_us=None, seq=None,
                  valid=False, x_um=None, vx_mm_s=None)
    if len(parts) == 3:
        if parts[2] != '0':
            raise ValueError('CART_STATE1 无效帧标志错误')
        return result
    if parts[4] != '1':
        raise ValueError('CART_STATE1 有效帧标志错误')
    result.update(sample_us=number(parts[2], 0, device),
                  seq=number(parts[3], 1, 2**64-1), valid=True,
                  x_um=number(parts[5], -2**31, 2**31-1),
                  vx_mm_s=number(parts[6], -2**31, 2**31-1))
    return result
