"""速度窗口有效性门禁；不证明磁场正常、位置真实或链路端到端延迟。"""
import time


class VelocityValidity:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.flags = None
        self.received_at = None
        self.active = False
        self.failed = False

    def update(self, parts):
        if self.active:
            self.ready()  # 迟到心跳不得掩盖此前的失效或超时。
        valid = len(parts) == 3 and all(p in ('0', '1') for p in parts[1:])
        self.flags = tuple(map(int, parts[1:])) if valid else None
        self.received_at = self.clock()
        if self.flags != (1, 1) and self.active:
            self.failed = True
        return self.ready()

    def ready(self):
        good = (self.flags == (1, 1) and self.received_at is not None
                and self.clock() - self.received_at <= .3)
        if not good and self.active:
            self.failed = True
        return good and not self.failed

    def require(self):
        if not self.ready():
            raise RuntimeError('速度窗口有效性未知、失效、超时或试验已中止；禁止继续运动')

    def command(self, line):
        parts = line.split()
        if parts and (parts[0] == 'ENABLE' or
                      (parts[0] == 'VEL' and (len(parts) != 2 or parts[1] != '0'))):
            self.require()
            self.active = True
