#!/usr/bin/env python3
"""Read-only SLT4 software trace capture. Never sends motion/configuration commands."""
import argparse
from state_frame import parse_state_frame
import json
import re
import time
from pathlib import Path

FIELDS = 'observed_us sample_us c_begin_us c_end_us e_um c_um sample_seq target_mm_s encoder_v_mm_s metadata sample_valid velocity_valid last_read_ok'.split()
BACKGROUND = re.compile(r'(?:MODE [A-Z_]+ [A-Z_]+|EVENT STEP_LOSS [0-9]+ [0-9]+ [0-9]+)')

class Capture:
    def __init__(self):
        self.header = None
        self.rows = []
        self.done = False

    def feed(self, line):
        if parse_state_frame(line) is not None:
            return None
        if BACKGROUND.fullmatch(line):
            return None
        if line.startswith('ERR '):
            raise ValueError(f'固件拒绝诊断：{line}')
        if self.done:
            raise ValueError('结束后重复诊断')
        parts = line.split()
        if len(parts) < 3 or parts[0] != 'SLT4':
            raise ValueError(f'不支持的诊断行：{line!r}')
        try:
            values = [int(v) for v in parts[2:]]
        except ValueError as e:
            raise ValueError('非整数诊断字段') from e
        if parts[1] == 'HEADER':
            if self.header is not None or len(values) != 5:
                raise ValueError('重复或不完整的HEADER')
            event, run, count, post, complete = values
            if event <= 0 or run <= 0 or not 0 <= post <= 32 or not post <= count <= 160 or complete != 1:
                raise ValueError('HEADER范围非法')
            self.header = dict(event_id=event, run_id=run, count=count, post_count=post)
        elif parts[1] == 'ROW':
            if self.header is None or len(values) != 15:
                raise ValueError('ROW长度或顺序非法')
            event, index, *fields = values
            if event != self.header['event_id'] or index != len(self.rows) or index >= self.header['count']:
                raise ValueError('事件混用、缺行或重复行')
            if any(v not in (0, 1) for v in fields[-4:]):
                raise ValueError('布尔字段非法')
            self.rows.append(dict(zip(FIELDS, fields)))
        elif parts[1] == 'END':
            if self.header is None or values != [self.header['event_id'], self.header['count']] or len(self.rows) != self.header['count']:
                raise ValueError('END不匹配或缺行')
            self.done = True
            return dict(version=4, **self.header, samples=self.rows,
                        scope='软件位置与缓存编码器的非同步观测，不证明物理脉冲或真实运动')
        else:
            raise ValueError('未知SLT4行')
        return None

def collect(stream, timeout=10.0):
    capture = Capture()
    # Discard a possible partial background line before issuing the query.
    stream.read_until(b'\n')
    if stream.write(b'STEPTRACE?\n') != len(b'STEPTRACE?\n'):
        raise ValueError('STEPTRACE命令未完整写入')
    deadline = time.monotonic() + timeout
    pending = bytearray()
    while time.monotonic() < deadline:
        pending.extend(stream.read(max(1, min(stream.in_waiting, 4096))))
        if len(pending) > 65536:
            raise ValueError('串口行缓冲超限')
        while b'\n' in pending:
            raw, _, pending = pending.partition(b'\n')
            result = capture.feed(raw.decode('ascii').rstrip('\r'))
            if result is not None:
                return result
    raise TimeoutError('STEPTRACE未完整结束，不生成成功报告')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--baud', type=int, default=460800)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('报告已存在，使用新的文件名')
    import serial
    with serial.Serial(args.port, args.baud, timeout=0.2, write_timeout=1) as stream:
        result = collect(stream)
    with args.out.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'已保存事件 {result["event_id"]}、运行 {result["run_id"]} 的 {result["count"]} 条软件轨迹：{args.out}')

if __name__ == '__main__':
    main()
