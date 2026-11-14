"""单向低速试验：plan 只查询；run 显式确认后才配置与运动。"""
import argparse
import json
import math
from pathlib import Path
from probe_link import Link, Abort, preflight


def validate(args):
    if not all(math.isfinite(v) for v in (args.velocity, args.acceleration, args.hold)):
        raise ValueError('参数必须有限')
    if not 1 <= args.velocity <= 20 or not 100 <= args.acceleration <= 100:
        raise ValueError('首轮试验限定正向1–20 mm/s、100 mm/s²')
    if not 0 < args.hold <= .5:
        raise ValueError('保持时间必须在(0,0.5]秒')
    return args.velocity * args.hold + args.velocity ** 2 / args.acceleration


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
