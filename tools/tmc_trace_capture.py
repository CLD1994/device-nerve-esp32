#!/usr/bin/env python3
"""采集 TMCT1/TMCT2 运行期驱动状态缓存；仅发送 TMCTRACE?，不使能、复位或运动。"""
import argparse
import json
import math
import re
import time
from pathlib import Path

BACKGROUND = re.compile(r'(?:STATE -?\d+ -?\d+ -?\d+ -?\d+|VEL_VALID [01] [01]|MODE [A-Z_]+ [A-Z_]+|EVENT STEP_LOSS \d+ \d+ \d+)')
# TMC2209 DRV_STATUS；与 components/tmc2209/tmc2209.c 位定义一致。
FLAGS = dict(otpw=0, ot=1, s2ga=2, s2gb=3, s2vsa=4, s2vsb=5,
             ola=6, olb=7, stealth=30, stst=31)

GSTAT_FLAGS = dict(reset=0, drv_err=1, uv_cp=2)
REGISTERS = {1: ("GSTAT", GSTAT_FLAGS), 111: ("DRV_STATUS", FLAGS)}


def decode_status(raw):
    return {**{name: bool(raw & (1 << bit)) for name, bit in FLAGS.items()},
            'cs_actual': (raw >> 16) & 31}


def _distribution(values):
    return dict(min=min(values), max=max(values), mean=sum(values)/len(values)) if values else None


def statistics(rows, flags=FLAGS):
    return dict(valid_count=sum(r['status'] == 0 for r in rows),
                busy_count=sum(r['status'] == 1 for r in rows),
                read_error_count=sum(r['status'] == 2 for r in rows),
                sample_interval_us=_distribution([b['begin_us']-a['begin_us'] for a,b in zip(rows,rows[1:])]),
                transaction_duration_us=_distribution([r['end_us']-r['begin_us'] for r in rows]),
                asserted_flag_counts={name:sum(r['decoded'] is not None and r['decoded'][name] for r in rows) for name in flags})


class Capture:
    def __init__(self):
        self.header = None
        self.version = None
        self.rows = []
        self.done = False

    def feed(self, line):
        if BACKGROUND.fullmatch(line):
            return None
        if line.startswith('ERR '):
            raise ValueError(f'固件拒绝诊断：{line}')
        if self.done:
            raise ValueError('结束后重复诊断')
        parts = line.split()
        if len(parts) < 3 or parts[0] not in ('TMCT1', 'TMCT2'):
            raise ValueError(f'不支持的诊断行：{line!r}')
        version = int(parts[0][-1])
        if self.version is not None and version != self.version:
            raise ValueError('诊断版本混用')
        if any(not re.fullmatch(r'\d+', v) for v in parts[2:]):
            raise ValueError('诊断字段必须为非负十进制整数')
        values = list(map(int, parts[2:]))
        if parts[1] == 'BEGIN':
            if self.header is not None or len(values) != 9:
                raise ValueError('BEGIN重复或长度错误')
            event,run,event_us,state,count,pre,period,window,ended = values
            pre_cap,post_cap = (40,102) if version == 1 else (80,204)
            if not (0 < event <= 0xffffffff and 0 < run <= 0xffffffff and
                    0 <= pre <= pre_cap and pre <= count <= pre_cap+post_cap and count-pre <= post_cap and
                    period == 50000 and window == 5000000 and state in (1,2) and
                    ended >= event_us and (state != 1 or ended >= event_us+window)):
                raise ValueError('BEGIN范围或完整时间窗错误')
            self.version = version
            self.header = dict(event_id=event,run_id=run,event_us=event_us,state=state,
                               count=count,pre_count=pre,period_us=period,
                               post_window_us=window,ended_us=ended)
        elif parts[1] == 'ROW':
            if self.header is None or len(values) != (7 if version == 1 else 8):
                raise ValueError('ROW长度或顺序错误')
            if version == 1:
                event,index,seq,begin,end,status,raw = values
                reg = 111
            else:
                event,index,seq,begin,end,status,reg,raw = values
            h=self.header
            if (event != h['event_id'] or index != len(self.rows) or index >= h['count'] or
                seq == 0 or end < begin or end > h['ended_us'] or
                status not in (0,1,2) or reg not in REGISTERS or raw > 0xffffffff or (status != 0 and raw != 0)):
                raise ValueError('ROW身份、序号、范围或时序错误')
            if end < max(0,h['event_us']-2000000) or end > h['event_us']+h['post_window_us']:
                raise ValueError('ROW超出事件窗口')
            if (index < h['pre_count'] and end > h['event_us']) or (index >= h['pre_count'] and end < h['event_us']):
                raise ValueError('ROW前后窗口分类错误')
            if self.rows and (seq <= self.rows[-1]['seq'] or begin < self.rows[-1]['end_us']):
                raise ValueError('ROW采样序列或事务时间倒序')
            decoded = None
            if status == 0:
                decoded = (decode_status(raw) if reg == 111 else
                           {name: bool(raw & (1 << bit)) for name,bit in GSTAT_FLAGS.items()})
            self.rows.append(dict(seq=seq,begin_us=begin,end_us=end,status=status,reg=reg,raw=raw,
                                  decoded=decoded))
        elif parts[1] == 'END':
            if self.header is None or values != [self.header['event_id'],self.header['count']] or len(self.rows) != self.header['count']:
                raise ValueError('END身份、行数错误或缺行')
            self.done=True
            stats = statistics(self.rows) if version == 1 else dict(by_register={
                name: statistics([r for r in self.rows if r['reg'] == reg], flags)
                for reg,(name,flags) in REGISTERS.items()})
            return dict(version=version,**self.header,samples=self.rows,statistics=stats,
                        scope='低频寄存器缓存；无告警不能排除采样间瞬态，失败或锁忙不是正常值；不证明电流、脉冲或机械运动')
        else:
            raise ValueError('未知TMCT诊断行')
        return None


def collect(stream, timeout=10.0):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('超时必须为有限正数')
    capture=Capture()
    stream.read_until(b'\n')
    request=b'TMCTRACE?\n'
    if stream.write(request) != len(request):
        raise ValueError('TMCTRACE命令未完整写入')
    deadline=time.monotonic()+timeout
    pending=bytearray()
    while time.monotonic() < deadline:
        pending.extend(stream.read(max(1,min(stream.in_waiting,4096))))
        if len(pending)>65536:
            raise ValueError('串口行缓冲超限')
        while b'\n' in pending:
            raw,_,pending=pending.partition(b'\n')
            result=capture.feed(raw.decode('ascii').rstrip('\r'))
            if result is not None:
                return result
    raise TimeoutError('TMCTRACE未完整结束，不生成成功报告')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port',required=True)
    ap.add_argument('--baud',type=int,default=460800)
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--timeout',type=float,default=10.0)
    args=ap.parse_args()
    if args.out.exists():
        ap.error('报告已存在，请使用新文件名')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        ap.error('超时必须为有限正数')
    import serial
    with serial.Serial(args.port,args.baud,timeout=0.2,write_timeout=1) as stream:
        result=collect(stream,args.timeout)
    with args.out.open('x',encoding='utf-8') as out:
        json.dump(result,out,ensure_ascii=False,indent=2)
    print(f'已保存事件 {result["event_id"]}、运行 {result["run_id"]} 的 {result["count"]} 条驱动状态：{args.out}')
    print(result['scope'])
    return 0


if __name__=='__main__':
    raise SystemExit(main())
