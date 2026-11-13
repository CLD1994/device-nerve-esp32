#!/usr/bin/env python3
"""手动启动四段往返：1250mm/s、ACC10000；不ENABLE/RESET/校准。"""
import argparse
import json
from pathlib import Path
from low_speed_probe import Link, Abort
from step50k_probe import stop_bounded, record_after_stop

SPEED=1250
ACCEL=10000
DECEL_ASSUMPTION=5000
INFLIGHT_S=.05
MARGIN_MM=50
STOP_TIMEOUT=1.0
LEG_SECONDS=1.0


def plan(cal,cfg):
    if cal['CAL_LENGTH_UM']!=853325 or cfg['X_MARGIN_UM']!=10000:
        raise Abort('本探针仅用于853325um已标定行程与10000um软余量')
    edge=cal['CAL_LENGTH_UM']/2000-cfg['X_MARGIN_UM']/1000
    reserve=SPEED*SPEED/(2*DECEL_ASSUMPTION)+SPEED*INFLIGHT_S+MARGIN_MM
    return dict(segments=['right','left','right','left'],speed_mm_s=SPEED,acceleration_mm_s2=ACCEL,
        outer_endpoint_mm=[-edge,edge],zero_request_position_mm=[-edge+reserve,edge-reserve],
        approach_speeds_mm_s=[100,20],approach_zero_distances_mm=[25,4],endpoint_tolerance_mm=5,
        normal_reserve_mm=reserve,normal_decel_assumption=DECEL_ASSUMPTION,
        inflight_assumption_ms=50,extra_margin_mm=MARGIN_MM,watchdog_ms=100,watchdog_decel=5000,
        fault_reserve_mm=SPEED*(INFLIGHT_S+.1)+SPEED*SPEED/(2*5000)+MARGIN_MM,
        per_leg_nonzero_limit_s=LEG_SECONDS,driver_current_requested_ma=1500,
        driver_current_verified_by_script=False,physical_stop_bound_verified=False,
        warning='端点为不可跨越外界，不保证精确抵达；按正常制动假设提前发0。故障/在途/断电时不能保证停距；1.5A须人工核实，脚本不设置电流。')


def execute(link,args):
    link.wait(lambda: link.aligned and link.state is not None,.5)
    link.mode=None;link.send('QUERY');link.wait(lambda: link.mode is not None)
    if link.mode not in (('DISABLED','NONE'),('READY','NONE')):raise Abort('当前故障或模式不允许，不自动复位')
    cal=link.query('CALIB?',['CAL_STATE','CAL_LENGTH_UM','CAL_SAVED','CAL_STORAGE'])
    if cal['CAL_STATE']!=2 or cal['CAL_SAVED']!=1 or cal['CAL_STORAGE']!=0:raise Abort('当前位置参考未确认或标定存储异常')
    keys=['VEL_MAX','ACC_MAX','WDT_MS','WDT_DEC','X_MARGIN_UM','POLE_ZERO_URAD','POLE_INV','X_INV','STEP_LOSS_UM']
    cfg=link.query('CONFIG?',keys)
    p=plan(cal,cfg);link.record('roundtrip_plan',p)
    if args.command=='plan':return p
    if not (args.confirm_motion and args.confirm_clearance and args.accept_stopping_risk):
        raise Abort('需要现场运动、净空及条件停距风险确认')
    link.fresh()  # READY only; no automatic recovery from existing FAULT.
    left=p['outer_endpoint_mm'][0]*1000
    if not left<link.state[0]<=left+5000:raise Abort('需人工在名义左端点内侧5mm内静止起步；不可贴挡块，不自动定位')
    link.velocity_validity.active=True
    failure=None;last_attempt=None
    print('四段1250/10000；外界±%.4fmm，提前零速触发±%.4fmm。条件停车假设非物理保证；不自动ENABLE/RESET。'%
          (p['outer_endpoint_mm'][1],p['zero_request_position_mm'][1]))
    try:
        stop_bounded(link,STOP_TIMEOUT)
        wanted=dict(VEL_MAX=SPEED,ACC_MAX=ACCEL,WDT_MS=100,WDT_DEC=5000)
        for k,v in wanted.items():
            if link.query('CONFIG %s %d'%(k,v),[k])[k]!=v:raise Abort('配置回执不匹配: '+k)
        actual=link.query('CONFIG?',list(cfg))
        if any(actual[k]!=wanted.get(k,v) for k,v in cfg.items()):raise Abort('配置读回不一致')
        link.record('applied_config',actual)
        edge=p['outer_endpoint_mm'][1]*1000
        trigger=p['zero_request_position_mm'][1]*1000
        for index,direction in enumerate((1,-1,1,-1),1):
            stop_bounded(link,STOP_TIMEOUT,not_before=None if last_attempt is None else last_attempt+INFLIGHT_S)
            link.fresh(); start_x=link.state[0]
            if direction*(direction*trigger-start_x)<=30000:raise Abort('本段到提前制动触发点不足30mm，拒绝启动')
            def guard(state, direction=direction, start_x=start_x):
                x,_,v,_=state
                if abs(x)>=edge:raise Abort('跨越内侧软边界')
                if abs(v)>SPEED:raise Abort('报告速度超过1250')
                if direction*(x-start_x)<-3000:raise Abort('本段反向位移超过3mm')
            link.guard=guard;guard(link.fresh())
            link.record('segment_start',dict(index=index,direction=direction,start_x_um=start_x,
                                            zero_trigger_um=direction*trigger))
            deadline=None;last_send=None;next_send=0.;previous=link.states;waiting=link.clock()+.1
            def check_time():
                now=link.clock()
                if last_send is not None and now-last_send>=.05:raise Abort('50ms续发截止；取消剩余各段')
                if deadline is not None and now>=deadline:raise Abort('本段时间上界到期；不以时间替代位置端点')
                if deadline is None and now>=waiting:raise Abort('等待新状态超时')
            while True:
                check_time();link.poll();check_time();state=link.fresh()
                if link.guard_failure:raise Abort(link.guard_failure)
                if direction*state[0]>=trigger:break
                now=link.clock()
                if now>=next_send and link.states!=previous:
                    previous=link.states;last_send=now;next_send=now+.025
                    if deadline is None:deadline=now+LEG_SECONDS
                    last_attempt=link.clock();link.record('nonzero_attempt',dict(segment=index,t=last_attempt))
                    link.send('VEL %d'%(direction*SPEED))
                link.sleep(.002)
            link.send('VEL 0')
            stop_bounded(link,STOP_TIMEOUT,not_before=last_attempt+INFLIGHT_S)
            link.record('cruise_stopped',dict(index=index,x_um=link.fresh()[0]))
            # Explicit normal-only slow phase, never a recovery from failed movement.
            for approach_speed,stand_off in ((100,25000),(20,4000)):
                link.record('approach_start',dict(index=index,speed_mm_s=approach_speed,nominal_endpoint_um=direction*edge))
                approach_deadline=link.clock()+20.; previous=link.states; last_send=None; next_send=0.
                while direction*link.fresh()[0]<edge-stand_off:
                    if link.clock()>=approach_deadline:raise Abort('低速接近20秒截止；取消剩余段')
                    if last_send is not None and link.clock()-last_send>=.05:raise Abort('低速接近50ms续发截止')
                    link.poll();state=link.fresh()
                    if link.guard_failure:raise Abort(link.guard_failure)
                    if link.clock()>=approach_deadline:raise Abort('低速接近20秒截止')
                    if last_send is not None and link.clock()-last_send>=.05:raise Abort('低速接近50ms续发截止')
                    if direction*state[0]>=edge-stand_off:break
                    if link.clock()>=next_send and link.states!=previous:
                        previous=link.states;last_send=link.clock();next_send=last_send+.025
                        last_attempt=link.clock();link.record('nonzero_attempt',dict(segment=index,phase='approach',t=last_attempt))
                        link.send('VEL %d'%(direction*approach_speed))
                    link.sleep(.01)
                link.send('VEL 0')
                stop_bounded(link,STOP_TIMEOUT,not_before=last_attempt+INFLIGHT_S)
            final_x=link.fresh()[0]
            if not edge-5000<=direction*final_x<edge:
                raise Abort('实际停点不在名义端点内侧5mm内，取消反向，不自动补偿')
            link.record('segment_stopped',dict(index=index,x_um=final_x,nominal_endpoint_um=direction*edge,
                                              remaining_um=edge-direction*final_x,evidence='received_state_stable'))
            # Next direction is permitted only after the above fresh stable observation.
        link.record('four_segments_observed',True)
    except (Exception,KeyboardInterrupt) as exc:failure=exc
    finally:
        try:link.send('VEL 0')
        except (Exception,KeyboardInterrupt) as exc:failure=Abort('%s；零速请求失败:%s'%(failure or '结束',exc))
        try:
            stop_bounded(link,STOP_TIMEOUT,not_before=None if last_attempt is None else last_attempt+INFLIGHT_S)
            status=('stop','received_state_stable')
        except (Exception,KeyboardInterrupt) as exc:
            failure=Abort('%s；停车未确认:%s'%(failure or '结束',exc));status=('stop_unconfirmed',str(exc))
        error=record_after_stop(link,*status)
        if error:failure=Abort('%s；日志失败:%s'%(failure or '结束',error))
    if failure is not None:raise Abort(str(failure)) from failure
    link.record('result','four_segments_stopped_not_physical_tracking_proof')
    return p


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['plan','run'])
    parser.add_argument('--port',required=True);parser.add_argument('--baud',type=int,default=460800)
    parser.add_argument('--out',required=True)
    for k in ('confirm-motion','confirm-clearance','accept-stopping-risk'):parser.add_argument('--'+k,action='store_true')
    args=parser.parse_args(argv)
    import serial
    with Path(args.out).open('x',encoding='utf8') as output:
        with serial.Serial(args.port,args.baud,timeout=0,write_timeout=.02) as port:
            link=Link(port)
            try:
                p=execute(link,args);print(json.dumps(p,ensure_ascii=False,indent=2))
                print('仅计划，无运动。' if args.command=='plan' else '四段接收停稳检查完成，未自动DISABLE。')
                return 0
            except (Exception,KeyboardInterrupt) as exc:
                record_after_stop(link,'aborted',str(exc));print('中止，不再执行后续段:',exc);return 1
            finally:
                for event in link.events:output.write(json.dumps(event,ensure_ascii=False)+'\n')

if __name__=='__main__':raise SystemExit(main())
