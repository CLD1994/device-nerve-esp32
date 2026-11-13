#!/usr/bin/env python3
"""单次正向1250 mm/s、9000 mm/s²探针；未知预算拒绝run，绝不自动ENABLE。"""
import argparse
import json
from pathlib import Path
from low_speed_probe import Link, Abort, preflight
from step50k_plan import calculate, TARGET_SPEED_MM_S, TARGET_ACCEL_MM_S2, TRAVEL_MM, SOFT_MARGIN_MM


def budget_for(link, args, cal, cfg):
    if cal['CAL_LENGTH_UM'] != round(TRAVEL_MM * 1000) or cfg['X_MARGIN_UM'] != round(SOFT_MARGIN_MM * 1000):
        raise Abort('实机行程/软边界与预算器不一致，拒绝沿用预算')
    return calculate(hold_s=args.hold_s, normal_decel=args.normal_decel,
                     watchdog_decel=args.watchdog_decel, watchdog_ms=args.watchdog_ms,
                     inflight_ms=args.inflight_ms, margin_mm=args.margin_mm,
                     window_s=args.window_s,
                     start_from_left_mm=link.state[0] / 1000 + TRAVEL_MM / 2)


def stop_reserve_mm(args):
    """在操作者给定在途上界下，两种停车路径取较大者。"""
    v=TARGET_SPEED_MM_S
    inflight=v*args.inflight_ms/1000
    normal=inflight+v*v/(2*args.normal_decel)
    watchdog=inflight+v*args.watchdog_ms/1000+v*v/(2*args.watchdog_decel)
    return max(normal,watchdog)+args.margin_mm


def validate_run(args, budget):
    if not args.confirm_motion or not args.confirm_clearance:
        raise Abort('run需要明确运动与现场净空确认')
    required = ('hold_s','margin_mm','normal_decel','watchdog_decel','watchdog_ms','inflight_ms','window_s')
    if any(getattr(args,k) is None for k in required):
        raise Abort('保持时间、制动能力、窗口、在途预算或余量尚未明确')
    if args.watchdog_ms < 100:
        raise Abort('固定25ms续发/50ms截止只支持WDT_MS至少100；拒绝可能超时后重启的节拍')
    for name in ('normal_decel_evidence','watchdog_decel_evidence','inflight_evidence'):
        if not isinstance(getattr(args,name),str) or not getattr(args,name).strip():
            raise Abort('缺少证据说明: ' + name)
    if args.margin_mm <= 0 or args.normal_decel > TARGET_ACCEL_MM_S2:
        raise Abort('额外余量必须为正，正常制动能力不能高于将设置的ACC_MAX')
    if not budget['conditional_fault_budget_fits'] or not budget['conditional_normal_budget_fits']:
        raise Abort('条件停止距离预算超出前方可用行程')
    # 达速判断迟到时仍可能走满整个窗口，正常停车同样按整个窗口预算。
    normal_window = TARGET_SPEED_MM_S * (args.window_s + args.inflight_ms/1000) + TARGET_SPEED_MM_S**2/(2*args.normal_decel) + args.margin_mm
    if normal_window > budget['forward_clearance_mm']:
        raise Abort('绝对非零窗口后的正常停车预算不足')


def record_after_stop(link, direction, value):
    """停止处理之后的尽力记录；调用者必须保留并报告失败。"""
    try:
        link.record(direction,value)
    except (Exception,KeyboardInterrupt) as exc:
        return '%s: %s' % (direction,exc)
    return None


def stop_bounded(link, timeout, not_before=None):
    observation_start=max(link.clock(), not_before if not_before is not None else link.clock())
    deadline=observation_start+timeout
    next_zero=0.; stable=None; low=high=None; errors=[]
    while link.clock() < deadline:
        if link.clock() >= next_zero:
            try: link.send('VEL 0')
            except Exception as exc: errors.append(str(exc))
            next_zero=link.clock()+.025
        try:
            link.poll(); state=link.fresh()
            if link.guard_failure: raise Abort(link.guard_failure)
        except Exception as exc:
            errors.append(str(exc)); stable=None; link.sleep(.005); continue
        if link.clock() < observation_start:
            stable=None; low=high=None
            link.sleep(.005)
            continue
        if link.batch:
            if any(abs(s[2])>1 for s in link.batch): stable=None
            else:
                now=link.clock()
                if stable is None: stable,low,high=now,state[0],state[0]
                low=min(low,*(s[0] for s in link.batch)); high=max(high,*(s[0] for s in link.batch))
                if high-low>100: stable,low,high=now,state[0],state[0]
                elif now-stable>=.2:
                    if errors: raise Abort('停车期间出现异常: '+errors[0])
                    return
        link.sleep(.005)
    raise Abort('停车未确认；使用现场独立断电措施，不能报告试验成功')


def execute(link,args):
    cal,cfg,_=preflight(link,args)
    budget=budget_for(link,args,cal,cfg)
    link.record('plan',budget)
    link.record('operator_declaration',dict(
        source='operator_statement',independently_verified=False,
        normal_decel_evidence=args.normal_decel_evidence,
        watchdog_decel_evidence=args.watchdog_decel_evidence,
        inflight_evidence=args.inflight_evidence,parameters=budget['inputs']))
    if args.command=='plan': return budget
    validate_run(args,budget)
    print("条件预算不是物理停车保证；晚到VEL可再次喂狗。现场须核实20V、安装、净空及独立断电。")
    link.fresh()  # 必须READY；不自动使能。
    link.velocity_validity.active=True
    stop_timeout=TARGET_SPEED_MM_S/min(args.normal_decel,args.watchdog_decel)+args.watchdog_ms/1000+.5
    failure=None
    last_nonzero_attempt=None
    reached=None
    motion_end_reason=None
    try:
        stop_bounded(link,stop_timeout)
        desired=dict(VEL_MAX=int(TARGET_SPEED_MM_S),ACC_MAX=int(TARGET_ACCEL_MM_S2),
                     WDT_MS=args.watchdog_ms,WDT_DEC=args.watchdog_decel)
        for name,value in desired.items():
            if link.query('CONFIG %s %d'%(name,value),[name])[name] != value:
                raise Abort('配置回执不匹配: '+name)
        actual=link.query('CONFIG?',list(cfg))
        if any(actual[k] != desired.get(k,v) for k,v in cfg.items()):
            raise Abort('配置读回不一致或其它参数改变')
        stop_bounded(link,stop_timeout)
        link.fresh()
        budget=budget_for(link,args,cal,actual); validate_run(args,budget)
        link.record('applied_config',actual)
        start_x=link.state[0]; edge=cal['CAL_LENGTH_UM']/2-cfg['X_MARGIN_UM']
        needed_mm=stop_reserve_mm(args)
        def guard(state):
            x,_,v,_=state
            if abs(x)>=edge or x<start_x-3000: raise Abort('越界或反向')
            if abs(v)>TARGET_SPEED_MM_S: raise Abort('报告速度超过预算速度；不扩大阈值继续')
            if (edge-x)/1000 <= needed_mm: raise Abort('前方停止距离预算不足')
        link.guard=guard
        guard(link.fresh())
        deadline=None; last_send=None; next_send=0.; reached=None
        first_deadline=link.clock()+.1; previous=link.states
        def deadlines():
            now=link.clock()
            if deadline is None:
                if now>=first_deadline: raise Abort('起步等待新状态超时')
            elif now-last_send>=.05:
                raise Abort('50ms续发截止已过，禁止继续非零命令')
            return deadline is not None and now>=deadline
        while True:
            if deadlines():
                motion_end_reason='window_elapsed'; break
            link.poll()
            if deadlines():
                motion_end_reason='window_elapsed'; break
            now=link.clock(); state=link.fresh()
            if link.guard_failure: raise Abort(link.guard_failure)
            if last_send is not None and state[2]>=TARGET_SPEED_MM_S*.98:
                if reached is None: reached=now
            if reached is not None and now-reached>=args.hold_s:
                motion_end_reason='approx_target_hold_completed'; break
            if now>=next_send and link.states!=previous:
                if deadlines():
                    motion_end_reason='window_elapsed'; break
                previous=link.states
                last_send=link.clock()
                if deadline is None: deadline=last_send+args.window_s
                next_send=last_send+.025
                last_nonzero_attempt=link.clock()
                link.record('nonzero_attempt',last_nonzero_attempt)
                link.send('VEL 1250')
            link.sleep(.002)
    except (Exception,KeyboardInterrupt) as exc:
        failure=exc
    finally:
        # 首次零速不能依赖clock、日志或停止循环的初始化成功。
        # Link.send先write后record；后者失败也已尝试发送，但不能据此声称停稳。
        first_stop_error=None
        try:
            link.send('VEL 0')
        except (Exception,KeyboardInterrupt) as exc:
            first_stop_error=exc
        horizon=None if last_nonzero_attempt is None else last_nonzero_attempt+args.inflight_ms/1000
        stop_error=None
        # 任何日志记录之前无条件进入有界停车，日志失败不能阻止VEL 0。
        try:
            stop_bounded(link,stop_timeout,not_before=horizon)
        except (Exception,KeyboardInterrupt) as exc:
            stop_error=exc
        log_errors=[]
        for direction,value in (
                ('motion_end',dict(reason=motion_end_reason or 'aborted',
                    approx_target_reached=reached is not None,
                    threshold_mm_s=TARGET_SPEED_MM_S*.98,
                    target_mm_s=TARGET_SPEED_MM_S,
                    exact_speed_verified=False)),
                ('inflight_horizon',horizon),
                ('stop_unconfirmed',str(stop_error)) if stop_error is not None else
                ('stop','received_state_stable_after_declared_inflight_horizon')):
            error=record_after_stop(link,direction,value)
            if error:log_errors.append(error)
        if first_stop_error is not None:
            failure=Abort("%s；首次零速请求/记录异常：%s" % (failure or "试验结束",first_stop_error))
        if stop_error is not None:
            failure=Abort("%s；停车未确认：%s" % (failure or "试验结束",stop_error))
        if log_errors:
            failure=Abort("%s；日志记录失败：%s" % (failure or "停止检查完成",'; '.join(log_errors)))
    if failure is not None: raise Abort(str(failure)) from failure
    error=record_after_stop(link,'result','completed_received_state_checks_not_physical_acceleration_proof')
    if error:raise Abort('日志记录失败：'+error)
    return budget


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['plan','run'])
    p.add_argument('--port',required=True);p.add_argument('--baud',type=int,default=460800)
    p.add_argument('--out',required=True)
    for key in ('hold-s','margin-mm','normal-decel','inflight-ms','window-s'):
        p.add_argument('--'+key,type=float)
    for key in ('watchdog-decel','watchdog-ms'):p.add_argument('--'+key,type=int)
    for key in ('normal-decel-evidence','watchdog-decel-evidence','inflight-evidence'):p.add_argument('--'+key)
    p.add_argument('--confirm-motion',action='store_true');p.add_argument('--confirm-clearance',action='store_true')
    args=p.parse_args(argv)
    import serial
    with Path(args.out).open('x',encoding='utf8') as output:
        with serial.Serial(args.port,args.baud,timeout=0,write_timeout=.02) as port:
            link=Link(port)
            try:
                result=execute(link,args)
                if args.command=='run':
                    end=next(e['value'] for e in reversed(link.events) if e['direction']=='motion_end')
                    print('运动结束原因:',end['reason'],'；近似到速:',end['approx_target_reached'],
                          '（报告速度≥1225，不代表精准1250或实际加速度）')
                print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
                print('计划完成，未运动。' if args.command=='plan' else '收到状态满足检查；未自动DISABLE，未证明实际加速度。')
                return 0
            except (Exception,KeyboardInterrupt) as exc:
                log_error=record_after_stop(link,'aborted',str(exc))
                print('试验中止:',exc)
                if log_error:print('日志记录失败:',log_error)
                return 1
            finally:
                for event in link.events:output.write(json.dumps(event,ensure_ascii=False)+'\n')


if __name__=='__main__':raise SystemExit(main())
