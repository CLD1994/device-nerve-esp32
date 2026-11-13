"""单向低速试验：plan 只查询；run 显式确认后才配置与运动。"""
import argparse
import json
import math
from pathlib import Path
import time
from velocity_validity import VelocityValidity


class Abort(RuntimeError):
    pass


class Link:
    def __init__(self, serial, clock=time.monotonic, sleep=time.sleep, log=None):
        self.serial, self.clock, self.sleep, self.log = serial, clock, sleep, log
        self.velocity_validity = VelocityValidity(clock)
        self.events = []
        self.batch = []
        self.guard = None
        self.guard_failure = None
        self.buffer = b''
        self.aligned = False
        self.mode = None
        self.state = None
        self.received_at = None
        self.states = 0
        self.replies = {}

    def record(self, direction, value):
        # 运动期间只写内存，避免磁盘flush阻塞截止检查；完整会话后再落盘。
        if len(self.events) < 10000:
            self.events.append({'t': self.clock(), 'direction': direction, 'value': value})
        else:
            raise Abort('日志内存预算耗尽')


    def send(self, command):
        try:
            self.velocity_validity.command(command)
        except RuntimeError as exc:
            raise Abort(str(exc)) from exc
        data = (command + '\n').encode('ascii')
        if self.serial.write(data) != len(data):
            raise Abort('串口写入不完整')
        self.record('tx', command)

    def poll(self):
        # 每轮有界，不能让持续到达的数据饿死墙钟截止检查。
        self.batch = []
        data = self.serial.read(4096)
        if not data:
            return
        self.record('rx_hex', data.hex())
        self.buffer += data
        if len(self.buffer) > 16384:
            raise Abort('接收积压超出预算')
        if not self.aligned:
            if b'\n' not in self.buffer:
                return
            self.buffer = self.buffer.split(b'\n', 1)[1]
            self.aligned = True
        while b'\n' in self.buffer:
            raw, self.buffer = self.buffer.split(b'\n', 1)
            try:
                p = raw.decode('ascii').strip().split()
                if not p:
                    continue
                if p[0] == 'VEL_VALID':
                    if not self.velocity_validity.update(p):
                        self.state = self.received_at = None
                        self.batch = []
                        if self.velocity_validity.failed:
                            self.guard_failure = '速度窗口失效；试验中止'
                            raise Abort(self.guard_failure)
                    continue
                if p[0] == 'STATE' and len(p) == 5:
                    if not self.velocity_validity.ready():
                        self.state = self.received_at = None
                        continue
                    self.state = tuple(map(int, p[1:]))
                    self.batch.append(self.state)
                    if self.guard:
                        try:
                            self.guard(self.state)
                        except Abort as error:
                            self.guard_failure = str(error)
                            raise
                    self.states += 1
                    self.received_at = self.clock()
                elif p[0] == 'MODE' and len(p) == 3:
                    self.mode = tuple(p[1:])
                    if p[1] == 'FAULT':
                        raise Abort('固件故障: ' + p[2])
                elif p[0] == 'OK' and len(p) == 3:
                    value = int(p[2])
                    if p[1] in self.replies and self.replies[p[1]] != value:
                        raise Abort('冲突回执: ' + p[1])
                    self.replies[p[1]] = value
                else:
                    raise Abort('异常协议行: ' + repr(raw))
            except (ValueError, UnicodeError) as e:
                raise Abort('损坏协议行') from e

    def wait(self, condition, seconds=1.0):
        end = self.clock() + seconds
        while self.clock() < end:
            self.poll()
            if condition():
                return
            self.sleep(.002)
        raise Abort('等待回执/状态超时')

    def query(self, command, keys):
        self.replies = {}
        self.send(command)
        self.wait(lambda: all(k in self.replies for k in keys))
        return {k: self.replies[k] for k in keys}

    def fresh(self):
        try:
            self.velocity_validity.require()
        except RuntimeError as exc:
            raise Abort(str(exc)) from exc
        if self.state is None or self.clock() - self.received_at > .1:
            raise Abort('没有最近收到的有效状态')
        if self.mode != ('READY', 'NONE'):
            raise Abort('非 READY NONE')
        return self.state


def validate(args):
    if not all(math.isfinite(v) for v in (args.velocity, args.acceleration, args.hold)):
        raise ValueError('参数必须有限')
    if not 1 <= args.velocity <= 20 or not 100 <= args.acceleration <= 100:
        raise ValueError('首轮试验限定正向1–20 mm/s、100 mm/s²')
    if not 0 < args.hold <= .5:
        raise ValueError('保持时间必须在(0,0.5]秒')
    return args.velocity * args.hold + args.velocity ** 2 / args.acceleration


def preflight(link, args):
    # 先在持续遥测中对齐行边界，再发查询，避免丢弃查询回执。
    link.wait(lambda: link.aligned and link.state is not None, .5)
    link.mode = None
    link.send('QUERY')
    link.wait(lambda: link.mode is not None and link.state is not None)
    if link.mode not in (('DISABLED', 'NONE'), ('READY', 'NONE')):
        raise Abort('不允许的模式')
    cal = link.query('CALIB?', ['CAL_STATE', 'CAL_LENGTH_UM', 'CAL_SAVED', 'CAL_STORAGE'])
    cfg = link.query('CONFIG?', ['VEL_MAX', 'ACC_MAX', 'WDT_MS', 'WDT_DEC', 'X_MARGIN_UM',
                                'POLE_ZERO_URAD', 'POLE_INV', 'X_INV', 'STEP_LOSS_UM'])
    if cal['CAL_STATE'] != 2 or cal['CAL_SAVED'] != 1 or cal['CAL_STORAGE'] != 0:
        raise Abort('本次位置尚未有效标定或存储异常')
    if not 100000 <= cal['CAL_LENGTH_UM'] <= 1000000:
        raise Abort('行程无效')
    x = link.state[0]
    # 双向保留50 mm物理安全余量；这里单位仍是固件坐标，须人工尺量确认。
    bound = cal['CAL_LENGTH_UM'] // 2 - cfg['X_MARGIN_UM'] - 50000
    if bound <= 0 or abs(x) + 30000 >= bound:
        raise Abort('两侧位置余量不足')
    return cal, cfg, bound


def stopped(link, timeout=1.0):
    deadline = link.clock() + timeout
    stable_since = None
    low = high = None
    last = link.states
    next_zero = 0
    while link.clock() < deadline:
        if link.clock() >= next_zero:
            link.send('VEL 0')
            next_zero = link.clock() + .025
        if link.guard_failure:
            raise Abort(link.guard_failure)
        link.poll()
        state = link.fresh()
        if link.states != last:
            now = link.clock()
            if any(abs(frame[2]) > 1 for frame in link.batch):
                stable_since = None
                low = high = None
            else:
                if stable_since is None:
                    stable_since, low, high = now, state[0], state[0]
                low = min(low, *(frame[0] for frame in link.batch))
                high = max(high, *(frame[0] for frame in link.batch))
                if high - low > 100:
                    stable_since, low, high = now, state[0], state[0]
                elif now - stable_since >= .2:
                    return True
            last = link.states
        link.sleep(.005)
    raise Abort('未确认停稳')


def motion(link, args, bound):
    if abs(link.fresh()[2]) > 10:
        raise Abort('起步前速度不在静止范围')
    link.velocity_validity.active = True
    for name, value in [('VEL_MAX', args.velocity), ('ACC_MAX', args.acceleration),
                        ('WDT_MS', 100), ('WDT_DEC', 100)]:
        reply = link.query('CONFIG %s %d' % (name, value), [name])
        if reply[name] != value:
            raise Abort('配置回执值不匹配')
    stopped(link)
    start_x = link.fresh()[0]
    last_x = start_x
    def guard(state):
        nonlocal last_x
        x = state[0]
        if abs(x - last_x) > 3000:
            raise Abort('位置跳变超过3mm')
        last_x = x
        if abs(x) >= bound or x - start_x > 30000 or x - start_x < -3000:
            raise Abort('越过位置/反向预算')
    link.guard = guard
    start = link.clock()
    # 独立总运动截止，不等待遥测到速才启动计时。
    deadline = start + args.velocity / args.acceleration + args.hold + .1
    reached_at = None
    next_send = start
    previous = -1
    while True:
        now = link.clock()
        if now >= deadline:
            raise Abort('总运动窗口截止')
        link.poll()
        now = link.clock()
        if now >= deadline:
            raise Abort('总运动窗口截止')
        x, _, vx, _ = link.fresh()
        if reached_at is None and vx > 0 and abs(vx - args.velocity) <= 1:
            reached_at = now
        if reached_at is not None and now - reached_at >= args.hold:
            break
        if now >= next_send:
            if link.states == previous:
                raise Abort('有效状态未继续更新，停止非零目标')
            previous = link.states
            link.send('VEL %d' % args.velocity)
            next_send = link.clock() + .025
        link.sleep(.002)
    stopped(link)


def execute(link, args):
    estimate = validate(args)
    cal, cfg, bound = preflight(link, args)
    link.record('preflight', {'calibration': cal, 'config': cfg})
    print('预计理想位移 %.2f mm，不是上界；非零窗口最多 %.3f s。' %
          (estimate, args.velocity / args.acceleration + args.hold + .1))
    print('run将设置VEL_MAX=%d ACC_MAX=%d WDT_MS=100 WDT_DEC=100，不恢复旧高值。'
          % (args.velocity, args.acceleration))
    print('无实时电压查询；请人工核实20V、独立断电、位置比例与两侧净空。')
    if args.command == 'plan':
        return
    if not args.confirm_motion:
        raise Abort('run必须明确提供--confirm-motion；不会自动ENABLE')
    # 从此处起任何失败都尝试停止；不以停止写入成功替代停稳。
    try:
        motion(link, args, bound)
    finally:
        try:
            link.send('VEL 0')
            stopped(link)
            link.record('stop', 'confirmed_by_received_velocity')
        except Exception as error:
            link.record('stop_unconfirmed', str(error))
            print('未确认停止，请使用独立断电。')
            raise Abort('停止未确认') from error


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', required=True)
    p.add_argument('--baud', type=int, default=460800)
    p.add_argument('--out', required=True, help='新建日志文件，不覆盖已有记录')
    p.add_argument('command', choices=['plan', 'run'])
    p.add_argument('--velocity', type=int, default=20)
    p.add_argument('--acceleration', type=int, default=100)
    p.add_argument('--hold', type=float, default=.5)
    p.add_argument('--confirm-motion', action='store_true')
    args = p.parse_args()
    validate(args)
    import serial
    # 非阻塞读、有限写超时，不调用可能无界等待的flush。
    with Path(args.out).open('x', encoding='utf8') as log:
        with serial.Serial(args.port, args.baud, timeout=0, write_timeout=.02) as port:
            link = Link(port, log=log)
            try:
                execute(link, args)
            except (Abort, OSError, KeyboardInterrupt) as e:
                link.record('aborted', str(e))
                print('试验中止:', e)
                return 1
            finally:
                for event in link.events:
                    log.write(json.dumps(event) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
