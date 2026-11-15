"""有界低速连续目标变化探针；不自动使能、回中或复位故障。"""
import argparse
import json
import time
from pathlib import Path

from probe_link import Link, Abort, preflight
from low_speed_probe import stopped

# 每段250ms，直接更新目标；物理换向仍由固件加减速处理。
TARGETS = (20, 5, 20, -20, -5, -20, 20, -20)
PHASE_S = .25
SEND_S = .025
CONFIG = {'VEL_MAX': 20, 'ACC_MAX': 100, 'WDT_MS': 100, 'WDT_DEC': 100}


class ProbeLink(Link):
    target = 0

    def poll(self):
        super().poll()
        if self.batch:
            # 同一串口批次不是同一设备采样时刻，保留顺序并标明主机接收时间。
            self.record('encoder_batch', {'target_mm_s': self.target,
                        'state_units': ['um', 'urad', 'mm/s', 'mrad/s'],
                        'states': self.batch[:]})

    def send(self, command):
        super().send(command)
        if command.startswith('VEL '):
            self.target = int(command.split()[1])


def run_motion(link, bound):
    if abs(link.fresh()[2]) > 1:
        raise Abort('起步前小车未静止')
    link.velocity_validity.active = True
    for key, value in CONFIG.items():
        reply = link.query('CONFIG %s %d' % (key, value), [key])
        if reply[key] != value:
            raise Abort('配置回执不匹配: ' + key)
    stopped(link)
    start_x = previous_x = link.fresh()[0]

    def guard(state):
        nonlocal previous_x
        x = state[0]
        if abs(x - previous_x) > 3000:
            raise Abort('编码器位置跳变超过3mm')
        previous_x = x
        if abs(x) >= bound or abs(x - start_x) >= 30000:
            raise Abort('越过位置边界或起点±30mm预算')

    link.guard = guard
    start = link.clock()
    deadline = start + PHASE_S * len(TARGETS)
    next_send = start
    previous_states = -1
    phase = -1
    link.record('sequence', {'targets_mm_s': TARGETS, 'phase_s': PHASE_S,
                'start_x_um': start_x, 'bound_abs_um': bound,
                'duration_s': deadline - start, 'clock': 'perf_counter'})
    while link.clock() < deadline:
        link.poll()
        link.fresh()
        now = link.clock()
        if now >= deadline:
            break
        if now - next_send > .05:
            raise Abort('主机发送调度落后超过50ms')
        current_phase = int((now - start) / PHASE_S)
        if current_phase > phase + 1:
            raise Abort('主机错过目标变化阶段')
        if now >= next_send or current_phase != phase:
            if link.states == previous_states:
                raise Abort('发送前没有更新的有效状态')
            previous_states = link.states
            phase = current_phase
            link.send('VEL %d' % TARGETS[phase])
            next_send = link.clock() + SEND_S
        link.sleep(.002)


def stop_and_disable(link):
    # 即使状态门控失败也先尝试零速；FAULT 不自动RESET。
    link.send('VEL 0')
    try:
        stopped(link)
    except Exception as error:
        link.record('stop_unconfirmed', str(error))
        print('未确认停稳，请人工核实并使用独立断电；不自动清除故障。')
        raise
    link.send('DISABLE')
    link.wait(lambda: link.mode == ('DISABLED', 'NONE'), 1)
    link.record('stop', 'encoder_stopped_and_disabled')


def execute(link, args):
    try:
        cal, cfg, bound = preflight(link, args)
        link.record('preflight', {'calibration': cal, 'config': cfg})
        print('8段×250ms，共2秒；目标(mm/s): ' + ', '.join(map(str, TARGETS)))
        print('run设置VEL_MAX=20 ACC_MAX=100 WDT_MS=100 WDT_DEC=100，不恢复旧高值。')
        print('无自动回中；保留两端余量、起点±30mm预算。需人工核实20V、两侧净空及独立断电。')
        if args.command == 'plan':
            return
        run_motion(link, bound)
    finally:
        if args.command == 'run':
            stop_and_disable(link)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--baud', type=int, default=460800)
    parser.add_argument('--out', required=True, help='新建JSONL日志，不覆盖已有文件')
    parser.add_argument('command', choices=['plan', 'run'])
    parser.add_argument('--confirm-motion', action='store_true')
    args = parser.parse_args()
    if args.command == 'run' and not args.confirm_motion:
        parser.error('run必须明确提供--confirm-motion；现场先READY，不自动ENABLE')
    import serial
    with Path(args.out).open('x', encoding='utf8') as log:
        with serial.Serial(args.port, args.baud, timeout=0, write_timeout=.02) as port:
            link = ProbeLink(port, clock=time.perf_counter, log=log)
            try:
                execute(link, args)
            except (Abort, OSError, KeyboardInterrupt) as error:
                link.record('aborted', str(error))
                print('试验中止:', error)
                return 1
            finally:
                for event in link.events:
                    log.write(json.dumps(event, ensure_ascii=False) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
