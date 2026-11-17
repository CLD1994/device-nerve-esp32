"""自然下垂零点标定。只改 POLE_ZERO_URAD，保留方向，不运动。"""
import math
import re
import time
from state_frame import parse_state_frame

PI = 3141592
PERIOD = 6283185


def wrap(value):
    return (value + PI) % PERIOD - PI


def estimate_zero(angles, old_zero, inverted):
    """当前角度环形均值 → 下垂为 π；返回固件允许范围内的零点。"""
    if not angles or inverted not in (0, 1) or not -PI <= old_zero <= PI:
        raise ValueError('零点、方向或样本无效')
    if any(not -PI <= a <= PI for a in angles):
        raise ValueError('摆角越界')
    scale = 2 * math.pi / PERIOD
    mean = math.atan2(sum(math.sin(a * scale) for a in angles),
                      sum(math.cos(a * scale) for a in angles)) / scale
    offsets = [wrap(a - mean) for a in angles]
    if max(offsets) - min(offsets) > 8727:  # 0.5 degree peak-to-peak
        raise ValueError('摆杆尚未稳定：角度跨度超过 0.5°')
    zero = wrap(round(old_zero + (-1 if inverted else 1) * mean + PI))
    return int(zero)


class CalibrationSession:
    """依赖注入：串口提供 read_until/write/reset_input_buffer，clock 为单调秒。"""
    def __init__(self, serial, clock=time.monotonic):
        self.serial, self.clock = serial, clock
        self.guard = None

    def send(self, command):
        data = (command + '\n').encode('ascii')
        if self.serial.write(data) != len(data):
            raise RuntimeError('串口写入不完整；配置可能已写入，请查询 dump')

    def read(self):
        raw = self.serial.read_until(b'\n', size=257)
        if not raw:
            raise RuntimeError('没有新接收数据；停止标定')
        if not raw.endswith(b'\n') or len(raw) > 256:
            raise RuntimeError('串口行不完整或过长')
        line = raw[:-1].removesuffix(b'\r').decode('ascii')
        if line.startswith('ERR '):
            raise RuntimeError('固件拒绝：' + line)
        if line.startswith('MODE ') and line != 'MODE DISABLED NONE':
            raise RuntimeError('只允许 DISABLED NONE 状态标定')
        return line

    def request(self, command, wanted):
        self.send(command)
        found = {}
        deadline = self.clock() + 1.5
        while self.clock() < deadline:
            line = self.read()
            if command == 'QUERY' and line == 'MODE DISABLED NONE':
                return None
            match = re.fullmatch(r'OK ([A-Z_]+) (-?[0-9]{1,10})', line)
            if match and match[1] in wanted:
                if match[1] in found:
                    raise RuntimeError('重复配置回执')
                found[match[1]] = int(match[2])
                if found.keys() == wanted:
                    return found
            elif line.startswith('STATE '):
                frame = parse_state_frame(line)
                if self.guard is not None:
                    self.guard(frame)
        raise RuntimeError('查询超时；未写入或未确认配置')

    def settings(self):
        result = self.request('CONFIG?', {'POLE_ZERO_URAD', 'POLE_INV'})
        if result['POLE_INV'] not in (0, 1) or not -PI <= result['POLE_ZERO_URAD'] <= PI:
            raise RuntimeError('固件零点或方向不在合法范围')
        return result

    def calibrate(self):
        self.serial.reset_input_buffer()
        # 丢一条可能从中途开始的行；之后查询响应提供同一串口的顺序边界。
        self.serial.read_until(b'\n', size=257)
        self.request('QUERY', set())
        original = self.settings()
        angles = []
        start = last = self.clock()
        while self.clock() - start < 1.0:
            line = self.read()
            frame = parse_state_frame(line)
            if frame is None:
                continue
            now = self.clock()
            if now - last > .1:
                raise RuntimeError('采样接收间隔超过 100 ms')
            last = now
            if not frame['flags'] & 2:
                raise RuntimeError('摆杆测量无效；未写入零点')
            pole = frame['pole']
            if abs(pole['vth_mrad_s']) > 20:
                raise RuntimeError('摆杆仍在运动；未写入零点')
            angles.append(pole['theta_urad'])
        if len(angles) < 200 or self.clock() - last > .1:
            raise RuntimeError('有效采样不足；未写入零点')
        new_zero = estimate_zero(angles, original['POLE_ZERO_URAD'], original['POLE_INV'])
        def guard(frame):
            if not frame['flags'] & 2 or abs(frame['pole']['vth_mrad_s']) > 20:
                raise RuntimeError('校准期间摆杆测量失效或仍在运动')
            if abs(wrap(frame['pole']['theta_urad'] - angles[-1])) > 8727:
                raise RuntimeError('采样后摆角已变化；未写入零点')
        self.guard = guard
        if self.settings() != original:
            raise RuntimeError('采样期间参数已改变；未写入零点')
        self.request('QUERY', set())
        self.guard = None  # 写入后角度坐标改变，不能与旧零点下的采样直接比较。
        reply = self.request(f'CONFIG POLE_ZERO_URAD {new_zero}', {'POLE_ZERO_URAD'})
        if reply['POLE_ZERO_URAD'] != new_zero:
            raise RuntimeError('零点写入回执不匹配；请查询 dump')
        actual = self.settings()
        self.request('QUERY', set())
        if actual != dict(POLE_ZERO_URAD=new_zero, POLE_INV=original['POLE_INV']):
            raise RuntimeError('写后读回不一致；请查询 dump，不自动回滚')
        return original, actual


def calibrate_port(port, baud):
    import serial
    with serial.Serial(port, baud, timeout=.1, write_timeout=1) as link:
        old, new = CalibrationSession(link).calibrate()
    print(f"下垂零点已读回：{old['POLE_ZERO_URAD']} → {new['POLE_ZERO_URAD']} µrad；"
          f"POLE_INV={new['POLE_INV']} 不变。已由固件保存到 NVS。")
    return 0
