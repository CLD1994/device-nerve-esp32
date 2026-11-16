"""串口会话的测试替身：只模拟字节传输和经过的时间，不解析协议。"""
from collections import deque


class ManualClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class MemorySerial:
    """实现 Rig 使用的 pyserial 子集；每次 read 表示经过 1 ms。"""
    def __init__(self, clock):
        self.clock = clock
        self.chunks = deque([b'opening partial line\n'])
        self.writes = []
        self.closed = False
        self.write_limit = None
        self.open_options = None
        self.flush_count = 0

    def factory(self, port, baud, *, timeout, write_timeout):
        self.open_options = (port, baud, timeout, write_timeout)
        self.write_timeout = write_timeout
        return self

    def feed(self, *chunks):
        self.chunks.extend(chunks)

    def read(self, size):
        self.clock.advance(.001)
        if not self.chunks:
            return b''
        chunk = self.chunks.popleft()
        if len(chunk) > size:
            self.chunks.appendleft(chunk[size:])
        return chunk[:size]

    def write(self, data):
        sent = len(data) if self.write_limit is None else min(self.write_limit, len(data))
        self.writes.append(data[:sent])
        return sent

    def flush(self):
        self.flush_count += 1

    def close(self):
        self.closed = True


def session(rig_class, **kwargs):
    clock = ManualClock()
    transport = MemorySerial(clock)
    messages = []
    rig = rig_class('memory', serial_factory=transport.factory, clock=clock,
                    output=messages.append, **kwargs)
    return rig, transport, clock, messages


def receive(rig, transport, *lines):
    transport.feed(('\n'.join(lines) + '\n').encode('ascii'))
    rig.pump(.005)


def measurement_bytes(rig, x=0, theta=0, vx=0, vth=0, *, flags=3):
    """生成一个新的测量样本；不转换传入的旧协议文本。"""
    from state_test_support import state_line
    seq=(getattr(rig,'_fixture_seq',0)+1)&65535
    tick=max(getattr(rig,'_fixture_tick',0)+1,int(rig._clock()*1000000))
    rig._fixture_seq=seq;rig._fixture_tick=tick
    return state_line(x,theta,vx,vth,seq=seq,tick=tick&0xffffffff,flags=flags)


def receive_measurements(rig, transport, x=0, theta=0, vx=0, vth=0, *, flags=3):
    transport.feed(measurement_bytes(rig,x,theta,vx,vth,flags=flags))
    rig.pump(.005)
