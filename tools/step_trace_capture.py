#!/usr/bin/env python3
"""停稳后只读STEPTRACE?，不使能、复位或修改参数。"""
import argparse
import json
from pathlib import Path
import time

FIELDS = ('observed_us sample_us c_begin_us c_end_us e_um c_um sample_seq raw_counts '
          'target_mm_s encoder_v_mm_s metadata sample_valid last_read_ok encoder_v_valid '
          'engine_v_q16 engine_target_q16 engine_position_steps engine_stopped '
          'engine_timer_running wdt_stale_time_count wdt_expired_count').split()

FIELDS_V2 = FIELDS + ('pcnt_count pcnt_valid pcnt_init_error pcnt_read_error '
                      'pcnt_overflow_invalid pcnt_begin_us pcnt_end_us en_level en_read_error').split()

FIELDS_V3 = FIELDS_V2 + ('encoder_status frame_valid spi_rx0 spi_rx1 spi_rx2 spi_rx3 spi_rx4 spi_rx5').split()

def collect(ser, timeout=8.0):
    request = b'STEPTRACE?\n'
    if ser.write(request) != len(request):
        raise RuntimeError('STEPTRACE write incomplete')
    deadline = time.monotonic() + timeout
    record = None
    count = None
    while time.monotonic() < deadline:
        line = ser.readline().decode('ascii', errors='replace').strip()
        if line.startswith('ERR '):
            raise RuntimeError(line)
        if not line.startswith(('SLT1 ', 'SLT2 ', 'SLT3 ')):
            continue
        parts = line.split()
        if len(parts) < 4:
            raise ValueError('truncated STEPTRACE line')
        version = int(parts[0][-1])
        fields = {1: FIELDS, 2: FIELDS_V2, 3: FIELDS_V3}[version]
        event = int(parts[1])
        if parts[2] == 'BEGIN':
            if record is not None or len(parts) != 5:
                raise ValueError('duplicate/invalid BEGIN')
            count, run = map(int, parts[3:])
            if not 0 <= count <= 128:
                raise ValueError('invalid sample count')
            record = dict(version=version, event_id=event, run_id=run, samples=[])
        elif record is None or event != record['event_id'] or version != record['version']:
            raise ValueError('missing BEGIN or mixed event')
        elif parts[2] == 'ROW':
            if len(parts) != 4 + len(fields) or int(parts[3]) != len(record['samples']):
                raise ValueError('invalid row length/index')
            if len(record['samples']) >= count:
                raise ValueError('excess rows')
            record['samples'].append(dict(zip(fields, map(int, parts[4:]))))
        elif parts[2] == 'END':
            if len(parts) != 4 or int(parts[3]) != count or len(record['samples']) != count:
                raise ValueError('incomplete trace')
            return record
        else:
            raise ValueError('unknown STEPTRACE record')
    raise TimeoutError('STEPTRACE incomplete; no reset was sent')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--baud', type=int, default=460800)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('output already exists')
    import serial
    ser = serial.Serial(port=None, baudrate=args.baud, timeout=0.2, write_timeout=1)
    ser.dtr = False
    ser.rts = False
    ser.port = args.port
    try:
        ser.open()
        record = collect(ser)
    finally:
        ser.close()
    with args.out.open('x', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f"已保存事件 {record['event_id']} 的 {len(record['samples'])} 条监督轨迹：{args.out}")
    print('E/C/引擎/PCNT异步采样；PCNT仅MCU引脚输入路径计数，不证明驱动器接收或脉宽。')


if __name__ == '__main__':
    main()
