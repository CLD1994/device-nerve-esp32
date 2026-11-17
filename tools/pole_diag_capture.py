#!/usr/bin/env python3
"""停机后只读收集摆杆测量失效首证据；不清除、使能或发送运动命令。"""
import argparse
from state_frame import parse_state_frame
import json
import re
import time
from pathlib import Path

FIELDS=('observed_us sampled_us age_us fill required span_us gap_us seq failure_seq '
        'continuity_seq has_sample last_attempt_ok ok velocity_valid reason_bits raw_counts status').split()
BACKGROUND = re.compile(r'(?:MODE [A-Z_]+ [A-Z_]+|EVENT STEP_LOSS [0-9]+ [0-9]+ [0-9]+)')
def number(token, low=0, high=2**64-1):
    if not re.fullmatch(r'-?[0-9]{1,20}',token):raise ValueError('非法数字字段')
    value=int(token)
    if not low<=value<=high:raise ValueError('数字字段越界')
    return value

def sample(tokens):
    if len(tokens)!=len(FIELDS):raise ValueError('快照字段数量错误')
    out=dict(zip(FIELDS,[number(t,-2**63,2**63-1) if i in (0,1,2,5,6) else number(t) for i,t in enumerate(tokens)]))
    if (out['required'] not in (17,33) or out['fill']>out['required']
            or any(out[k] not in (0,1) for k in ('has_sample','last_attempt_ok','ok','velocity_valid'))
            or out['reason_bits']>255 or out['raw_counts']>2097151 or out['status']>7):
        raise ValueError('快照条件字段越界')
    return out

class Capture:
    def __init__(self):
        self.record=None
        self.expected='BEGIN'
        self.done=False
        self.raw=[]
    def feed(self,line):
        if len(line)>2048:raise ValueError('诊断行过长')
        if parse_state_frame(line) is not None:
            return None
        if BACKGROUND.fullmatch(line):return None
        if line.startswith('ERR '):raise ValueError('固件拒绝诊断：'+line)
        p=line.split(' ')
        if any(not token or any(ch.isspace() for ch in token) for token in p):
            raise ValueError('诊断字段必须由单个空格分隔')
        if self.done or len(p)<2 or p[0]!='POLED2' or p[1]!=self.expected:
            raise ValueError('未知、重复或顺序错误的诊断行：'+repr(line[:256]))
        kind=p[1];v=p[2:]
        if kind=='BEGIN':
            if len(v)!=6:raise ValueError('BEGIN字段数量错误')
            run=number(v[0],0,2**32-1);generation=number(v[1])
            captured=number(v[2],0,1);has_failure=number(v[3],0,1)
            transitions=number(v[4]);dropped=number(v[5])
            if has_failure and not captured:raise ValueError('没有事件却声明关联失败')
            if bool(transitions)!=bool(captured):raise ValueError('首事件与转换计数矛盾')
            self.record=dict(version=2,run_id=run,generation=generation,captured=bool(captured),has_failure=bool(has_failure),transitions=transitions,
                             dropped=dropped,before=None,after=None,failure=None)
            self.expected='BEFORE' if captured else 'END'
        elif kind in ('BEFORE','AFTER'):
            s=sample(v)
            if (kind=='BEFORE' and (s['reason_bits']!=0 or not s['velocity_valid'] or not all(s[k] for k in ('has_sample','ok')) or s['fill']!=s['required'] or not 0<=s['age_us']<=s['gap_us'] or not 0<s['span_us']<=32000)) or (kind=='AFTER' and (not s['reason_bits'] or s['velocity_valid'])):
                raise ValueError('有效到无效的快照条件矛盾')
            if kind=='AFTER':
                before=self.record['before']
                for key in ('observed_us','sampled_us','seq','failure_seq','continuity_seq'):
                    if s[key]<before[key]:raise ValueError('前后快照序列或时间倒退')
            self.record[kind.lower()]=s
            self.expected=('AFTER' if kind=='BEFORE' else
                           'FAIL' if self.record['has_failure'] else 'END')
        elif kind=='FAIL':
            if len(v)!=9:raise ValueError('FAIL字段数量错误')
            self.record['failure']=dict(kind=number(v[0],1,3),sequence=number(v[1]),
                observed_us=number(v[2],-2**63,2**63-1),bytes=[number(x,0,255) for x in v[3:]])
            failure=self.record['failure'];before=self.record['before'];after=self.record['after']
            if not (before['failure_seq']<failure['sequence']<=after['failure_seq']
                    and before['observed_us']<=failure['observed_us']<=after['observed_us']):
                raise ValueError('失败记录不属于本次有效性转换')
            self.expected='END'
        else:
            if (len(v)!=2 or number(v[0],0,2**32-1)!=self.record['run_id']
                    or number(v[1])!=self.record['generation']):
                raise ValueError('END运行身份不一致')
            self.done=True
        self.raw.append(line)
        if self.done:
            return dict(self.record,raw_lines=list(self.raw))
        return None

def collect(ser, timeout=3.0, clock=time.monotonic):
    # 对齐开串口的残行；之后只发送一个只读请求，不flush、不自动复位。
    alignment=ser.read_until(b'\n',size=16385)
    if len(alignment)>16384:raise ValueError('串口对齐残行超限')
    request=b'POLEDIAG?\n'
    if ser.write(request)!=len(request):raise ValueError('只读请求未完整写入')
    deadline=clock()+timeout
    capture=Capture();pending=bytearray()
    while clock()<deadline:
        waiting=ser.in_waiting
        if waiting>16384:raise ValueError('串口待接收积压超限')
        pending.extend(ser.read(min(waiting or 1,4096)))
        if len(pending)>16384:raise ValueError('串口缓冲超限')
        while b'\n' in pending:
            line,_,tail=pending.partition(b'\n');pending=bytearray(tail)
            result=capture.feed(line.decode('ascii').removesuffix('\r'))
            if result is not None:return result
    raise TimeoutError('未收到完整摆杆诊断；不保存部分结果')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port',required=True)
    ap.add_argument('--baud',type=int,default=460800)
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args()
    if a.out.exists():ap.error('输出文件已存在，请使用新文件名')
    import serial
    try:
        with serial.Serial(a.port,a.baud,timeout=.2,write_timeout=1) as ser:record=collect(ser)
    except (ValueError,UnicodeError,TimeoutError,serial.SerialException) as exc:
        raise SystemExit(str(exc)) from exc
    with a.out.open('x',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False,indent=2);f.write('\n')
    print('已保存运行 %d 的摆杆首因观测：%s'%(record['run_id'],a.out))
    print('首事件已捕获' if record['captured'] else '尚未捕获有效到无效事件；不代表运行中从未失效')
    print('FAIL仅在本次转换关联到新失败时出现；全零帧不能区分合法零角和线路全低。')
if __name__=='__main__':main()
