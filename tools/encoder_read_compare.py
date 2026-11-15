#!/usr/bin/env python3
"""DISABLED 下4秒 B/S/B/S 编码器SPI对照；不发送使能、运动、复位或参数写入。"""
import argparse
import json
from pathlib import Path
import time

FIELDS = ('phase begin_us end_us raw_counts status crc crc_expected valid first_in_phase '
          'reg003 reg004 reg005 reg006').split()

def collect(ser, timeout=15, announce=print):
    command = b'ENCODERTEST?\n'
    if ser.write(command) != len(command):
        raise RuntimeError('ENCODERTEST write incomplete')
    deadline = time.monotonic() + timeout
    rows = []
    expected = None
    started = False
    while time.monotonic() < deadline:
        line = ser.readline().decode('ascii', errors='replace').strip()
        if line.startswith('ERR '):
            raise RuntimeError(line)
        if not line.startswith('ERT1 '):
            continue
        parts = line.split()
        if parts[1] == 'START':
            if started or parts != ['ERT1', 'START', '4000']:
                raise ValueError('invalid START')
            started = True
            announce('开始4秒采样：缓慢手动往返小车，勿启动电机；B/S/B/S各1秒。')
        elif parts[1] == 'BEGIN':
            if not started or expected is not None or len(parts) != 3:
                raise ValueError('invalid BEGIN')
            expected = int(parts[2])
            if not 0 <= expected <= 810:
                raise ValueError('invalid count')
        elif parts[1] == 'ROW':
            if expected is None or len(parts) != 3+len(FIELDS) or int(parts[2]) != len(rows):
                raise ValueError('invalid ROW')
            if len(rows) >= expected:
                raise ValueError('excess rows')
            rows.append(dict(zip(FIELDS, map(int, parts[3:]))))
        elif parts[1] == 'END':
            if len(parts) != 3 or expected is None or int(parts[2]) != expected or len(rows) != expected:
                raise ValueError('incomplete END')
            return dict(version=1, duration_ms=4000, phases=['B', 'S', 'B', 'S'], samples=rows)
        else:
            raise ValueError('unknown ERT1 record')
    raise TimeoutError('未完整收到对照结果；工具未发送ENABLE/RESET，固件有独立4秒截止')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', required=True)
    p.add_argument('--baud', type=int, default=460800)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        p.error('output already exists')
    import serial
    ser = serial.Serial(port=None, baudrate=a.baud, timeout=.2, write_timeout=1)
    ser.dtr = False
    ser.rts = False
    ser.port = a.port
    print('请先保持DISABLED，准备在出现“开始4秒采样”后缓慢手动往返。', flush=True)
    try:
        ser.open()
        result = collect(ser, announce=lambda s: print(s, flush=True))
    finally:
        ser.close()
    with a.out.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    for phase, label in enumerate(result['phases']):
        rows = [x for x in result['samples'] if x['phase'] == phase]
        if rows:
            print(f'{phase}:{label} 保存{len(rows)}行，失败{sum(not x["valid"] for x in rows)}，'
                  f'留样最大读耗时{max(x["end_us"]-x["begin_us"] for x in rows)}us')
    print(f'报告：{a.out}')
    print('各段时间不同；S首帧可能释放旧影子，不能只看首帧。测试后不自动使能或重新定位。')

if __name__ == '__main__':
    main()
