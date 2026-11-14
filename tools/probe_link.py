"""运动探针共用串口会话与预检；串口、单调时钟和等待函数由调用方注入。"""
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


