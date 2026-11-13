"""固定400 mm/s、5000 mm/s²的单向试验；不自动使能。"""
import argparse
import json
from pathlib import Path
from low_speed_probe import Link, Abort, preflight

CONFIG = dict(VEL_MAX=400, ACC_MAX=5000, WDT_MS=100, WDT_DEC=5000)
WINDOW_S = .23
HOLD_S = .1
CLEARANCE_UM = 250000
STOP_UM = 100000
FAIL_UM = 200000


def stop(link):
    """有限等待并持续观察；协议/位置故障锁存，不阻止后续零速尝试。"""
    deadline = link.clock() + 1.0
    next_zero = 0
    stable = None
    low = high = None
    errors = []
    while link.clock() < deadline:
        if link.clock() >= next_zero:
            try:
                link.send('VEL 0')
            except Exception as error:
                errors.append(str(error))
            next_zero = link.clock() + .025
        try:
            link.poll()
            state = link.fresh()
        except Exception as error:
            errors.append(str(error))
            stable = None
            link.sleep(.005)
            continue
        if link.batch:
            if any(abs(s[2]) > 1 for s in link.batch):
                stable = None
            else:
                now = link.clock()
                if stable is None:
                    stable, low, high = now, state[0], state[0]
                low = min(low, *(s[0] for s in link.batch))
                high = max(high, *(s[0] for s in link.batch))
                if high - low > 100:
                    stable, low, high = now, state[0], state[0]
                elif now - stable >= .2:
                    if errors:
                        raise Abort('停止期间通信/状态异常: ' + errors[0])
                    return
        link.sleep(.005)
    raise Abort('未确认停稳；请立即使用独立断电')


def execute(link, args):
    cal, cfg, _ = preflight(link, args)
    edge = cal['CAL_LENGTH_UM'] // 2 - cfg['X_MARGIN_UM']
    if edge - abs(link.state[0]) < CLEARANCE_UM:
        raise Abort('两侧软件边界净空必须各至少250mm')
    link.record('preflight', dict(calibration=cal, config=cfg, mode=link.mode,
                                 state=link.state, soft_edge_um=edge))
    print('预检 MODE=%s STATE=%s CAL=%s' % (link.mode, link.state, cal))
    print('固定正向400mm/s ACC5000 hold0.1s；理想72mm，不是位移上界。')
    print('非零窗口0.23s；100mm触发停机/200mm严重越界；两侧净空≥250mm。')
    print('将设VEL_MAX400 ACC_MAX5000 WDT_MS100 WDT_DEC5000；不恢复旧配置。')
    print('无实时电压查询；须人工确认20V、真实净空/比例、独立断电可达。')
    if args.command == 'plan':
        print('PLAN完成：只查询，未配置/使能/运动。')
        return
    if not args.confirm_motion or not args.confirm_clearance:
        raise Abort('run需要--confirm-motion和--confirm-clearance')
    failure = []
    severe = [False]
    try:
        # 当前READY允许，但先清除旧目标并在旧参数下确认停稳。
        link.fresh()
        stop(link)
        for name, value in CONFIG.items():
            if link.query('CONFIG %s %d' % (name, value), [name])[name] != value:
                raise Abort('配置回执不匹配')
        actual = link.query('CONFIG?', list(cfg))
        if any(actual[k] != v for k, v in CONFIG.items()):
            raise Abort('配置读回不匹配')
        if actual['X_MARGIN_UM'] != cfg['X_MARGIN_UM'] or actual['X_INV'] != cfg['X_INV']:
            raise Abort('位置配置改变')
        link.record('applied_config', actual)
        stop(link)
        start_x = link.fresh()[0]
        if edge - abs(start_x) < CLEARANCE_UM:
            raise Abort('配置后净空不足')
        last_x = start_x
        def guard(state):
            nonlocal last_x
            x = state[0]
            if abs(x - last_x) > 3000 and not failure:
                failure.append("相邻位置跳变超过3mm")
            last_x = x
            delta = x - start_x
            if abs(x) >= edge or delta >= FAIL_UM or delta <= -3000:
                severe[0] = True
                if not failure: failure.append('严重越界或反向')
            elif delta >= STOP_UM and not failure:
                failure.append('正向100mm触发停机')
        link.guard = guard
        # 从首个非零写入之前开始；写入耗时也占用预算。
        deadline = link.clock() + WINDOW_S
        reached = None
        next_send = 0
        previous = link.states
        while True:
            if link.clock() >= deadline:
                raise Abort('非零窗口截止')
            link.poll()
            now = link.clock()
            if now >= deadline:
                raise Abort('非零窗口截止')
            state = link.fresh()
            if failure:
                raise Abort(failure[0])
            if reached is None and abs(state[2] - 400) <= 5:
                reached = now
            if reached is not None and now - reached >= HOLD_S:
                break
            if now >= next_send:
                if link.states == previous:
                    raise Abort('没有新接收状态；停止非零命令')
                if link.clock() >= deadline:
                    raise Abort('非零窗口截止')
                previous = link.states
                link.send('VEL 400')
                next_send = link.clock() + .025
            link.sleep(.002)
    finally:
        try:
            stop(link)
            link.record('stop', 'received_state_stable')
            if severe[0]:
                print('严重越界/反向，本次失败；请使用独立断电并检查装置。')
        except Exception as error:
            link.record('stop_unconfirmed', str(error))
            print('未确认停止，请立即使用独立断电。')
            raise
    if failure:
        raise Abort(failure[0])
    link.record('result', 'completed_received_state_checks')
    print('试验完成：收到的状态满足停稳检查；未自动DISABLE，电机可能仍保持使能。')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', required=True)
    p.add_argument('--baud', type=int, default=460800)
    p.add_argument('--out', required=True)
    p.add_argument('command', choices=['plan', 'run'])
    p.add_argument('--confirm-motion', action='store_true')
    p.add_argument('--confirm-clearance', action='store_true')
    args = p.parse_args()
    import serial
    with Path(args.out).open('x', encoding='utf8') as log:
        with serial.Serial(args.port, args.baud, timeout=0, write_timeout=.02) as port:
            link = Link(port)
            try:
                execute(link, args)
            except (Exception, KeyboardInterrupt) as error:
                link.record('aborted', str(error))
                print('试验中止:', error)
                return 1
            finally:
                for event in link.events:
                    log.write(json.dumps(event) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
