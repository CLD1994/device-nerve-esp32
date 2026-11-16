"""基于收到的位置的有限行程诊断；预算不是物理安全保证。"""
import math
import time


class Plan:
    def __init__(self, config, velocity, reserve_mm, inflight_ms):
        if 'WDT_DEC' in config:
            raise ValueError('检测到旧 WDT_DEC；行程工具要求统一 ACC_MAX 的新固件')
        required = ('CAL_STATE','CAL_SAVED','CAL_STORAGE','CAL_LENGTH_UM',
                    'VEL_MAX','ACC_MAX','WDT_MS','X_MARGIN_UM')
        if any(k not in config or not isinstance(config[k], int) for k in required):
            raise ValueError('标定/配置回执缺失或格式错误')
        if (config['CAL_STATE'],config['CAL_SAVED'],config['CAL_STORAGE']) != (2,1,0):
            raise ValueError('标定状态不支持行程规划')
        if any(config[k] <= 0 for k in ('CAL_LENGTH_UM','VEL_MAX','ACC_MAX','WDT_MS')) or config['X_MARGIN_UM'] < 0:
            raise ValueError('配置范围无效')
        if not velocity or abs(velocity) > config['VEL_MAX']:
            raise ValueError('目标速度为零或超过 VEL_MAX')
        if not all(math.isfinite(v) and v >= 0 for v in (reserve_mm,inflight_ms)):
            raise ValueError('余量/在途预算必须是非负有限数')
        self.config, self.velocity = config, velocity
        self.direction = 1 if velocity > 0 else -1
        self.physical_um = config['CAL_LENGTH_UM']//2
        self.soft_um = self.physical_um-config['X_MARGIN_UM']
        self.target_um = self.direction*(self.soft_um-reserve_mm*1000)
        self.inflight = inflight_ms/1000 + .1 # 主机允许STATE接收年龄另计100ms；非设备采样年龄。
        if config['WDT_MS'] <= 20:
            raise ValueError('WDT_MS 必须大于20ms保活间隔')
        if self.soft_um <= 0 or self.direction*self.target_um <= 0:
            raise ValueError('余量覆盖整个可用行程')

    def budget_mm(self, measured_velocity):
        v = max(abs(self.velocity),abs(measured_velocity))
        if v > self.config['VEL_MAX']:
            raise RuntimeError('收到的速度超过 VEL_MAX')
        # 两条停车路径共用 ACC_MAX；WDT 项只比正常停车多等待窗口。
        return v*(self.inflight+self.config['WDT_MS']/1000)+v*v/(2*self.config['ACC_MAX'])


class Guard:
    def __init__(self, plan, start_um):
        self.plan, self.extreme = plan, start_um
        self.start = start_um
        self.entered = abs(start_um) <= plan.soft_um
        if abs(start_um)>plan.physical_um:
            raise ValueError('起点超过标定物理范围')
        if plan.direction*start_um >= plan.direction*plan.target_um:
            raise ValueError('目标不在请求方向前方')

    def observe(self, x, vx):
        p = self.plan
        if abs(x)>p.physical_um or p.direction*x>p.soft_um:
            raise RuntimeError('收到的位置越过目标侧软件边界或物理边界')
        if self.entered and p.direction*x < -p.soft_um:
            raise RuntimeError('进入软件范围后退出起点侧边界')
        if abs(x)<=p.soft_um: self.entered=True
        if p.direction*(x-self.extreme) < -3000:
            raise RuntimeError('收到的位置反向移动超过 3 mm')
        if p.direction*(x-self.extreme) > 0:
            self.extreme = x
        return p.direction*(p.target_um-x)/1000 <= p.budget_mm(vx)


class Stillness:
    """只用新到STATE逐帧建立200ms、100µm范围停稳证据。"""
    def __init__(self, rig, not_before=0):
        self.rig, self.not_before = rig, not_before
        self.since = self.low = self.high = None
        self.confirmed = False
        self.last_seen = None

    def observe(self):
        x,_,vx,_=map(int,self.rig.last_state)
        now=self.rig._clock()
        if self.last_seen is not None and now-self.last_seen>.1:
            self.since=self.low=self.high=None
            self.confirmed=False
        self.last_seen=now
        if vx != 0 or now < self.not_before:
            self.since=self.low=self.high=None
            self.confirmed=False
            return
        if self.since is None:
            self.since,self.low,self.high=now,x,x
        self.low=min(self.low,x)
        self.high=max(self.high,x)
        if self.high-self.low>100:
            self.since,self.low,self.high=now,x,x
        self.confirmed=now-self.since>=.2


def run(rig, args, sleep=time.sleep):
    """查询、规划与有限执行。仅此路径使用有界非阻塞接收。"""
    def poll():
        rig.poll_available()
        sleep(.001)
    until=rig._clock()+.4
    rig.replies.clear()
    rig.last_mode=None
    for command in ('CALIB?','CONFIG?','QUERY'): rig.send_line(command)
    while rig._clock()<until: poll()
    p=Plan(dict(rig.replies),args.v,args.reserve_mm,args.inflight_ms)
    if rig.last_reply and rig.last_reply[0]=='ERR': raise RuntimeError('查询被固件拒绝')
    if not rig.state_is_fresh(): raise RuntimeError('没有新鲜位置状态')
    x,_,vx,_=map(int,rig.last_state)
    guard=Guard(p,x)
    if guard.observe(x,vx): raise RuntimeError('起点剩余距离不足制动预算')
    print('物理端 ±%.3f mm；软件端 ±%.3f mm；目标 %.3f mm；当前制动预算 %.3f mm'
          %(p.physical_um/1000,p.soft_um/1000,p.target_um/1000,p.budget_mm(vx)))
    if args.plan: return 0
    if rig.last_mode != ('READY','NONE'): raise RuntimeError('行程执行需要 READY NONE；不会自动 ENABLE')
    initial=Stillness(rig)
    rig.state_observer=initial.observe
    try:
        deadline=rig._clock()+2
        while not initial.confirmed:
            if rig._clock()>=deadline: raise RuntimeError('起步前停稳未确认')
            poll()
    finally:
        rig.state_observer=None
    braking=False
    def observe():
        nonlocal braking
        x,_,vx,_=map(int,rig.last_state)
        if guard.observe(x,vx): braking=True
    from collections import deque
    messages=deque(maxlen=128)
    old_output=rig._output
    rig._output=messages.append
    rig.state_observer=observe
    started=next_send=rig._clock()
    last_send=None
    gap_limit=min(.05,p.config['WDT_MS']/1000)
    error=None
    def observe_message(line):
        nonlocal error
        parts=line.split()
        if parts[:1]==['ERR'] or (parts[:1]==['MODE'] and parts!=['MODE','READY','NONE']):
            error=error or RuntimeError('行程收到异常协议行：'+line)
            rig.velocity_validity.failed=True
    rig.message_observer=observe_message
    stop_x=None
    confirmed=False
    try:
        try:
            while not braking:
                rig.poll_available()
                now=rig._clock()
                if now-started>=args.max_seconds: raise RuntimeError('达到最长期限；位置可能未更新')
                if rig.last_mode != ('READY','NONE'): raise RuntimeError('运动中模式不再 READY NONE')
                if not rig.state_is_fresh(): raise RuntimeError('运动中状态过旧')
                rig.velocity_validity.require()
                observe()
                if braking: break
                if last_send is not None and now-last_send>=gap_limit:
                    raise RuntimeError('非零续发间隔超限')
                if now>=next_send:
                    before=rig._clock()
                    rig.send_line('VEL %d'%args.v)
                    last_send=before
                    if rig._clock()-before>=gap_limit: raise RuntimeError('主机写入耗时超限')
                    next_send=rig._clock()+.02
                sleep(.001)
        except (RuntimeError,OSError,KeyboardInterrupt) as exc:
            error=exc
            rig.velocity_validity.failed=True
        finally:
            rig.state_observer=None
            stop_x=int(rig.last_state[0]) if rig.last_state else None
            rig.send_line('VEL 0')
        # 最后非零写入后的在途假设窗口过去后才累计停稳证据。
        stationary=Stillness(rig,max(rig._clock(),(last_send or started)+args.inflight_ms/1000))
        rig.state_observer=stationary.observe
        deadline=rig._clock()+2
        next_zero=rig._clock()+.02
        while rig._clock()<deadline:
            if rig._clock()>=next_zero:
                rig.send_line('VEL 0')
                next_zero=rig._clock()+.02
            try:
                rig.poll_available()
            except RuntimeError as exc:
                error=error or exc
                rig.velocity_validity.failed=True
                # 门禁继续锁存失败；仅零速清理，不恢复非零。
                stationary=Stillness(rig)
                rig.state_observer=stationary.observe
            if rig.last_mode != ('READY','NONE') or (rig.last_reply and rig.last_reply[0]=='ERR'):
                error=error or RuntimeError('停车期间模式/回执异常')
                rig.velocity_validity.failed=True
            if stationary.confirmed and rig.state_is_fresh():
                confirmed=True
                break
            sleep(.001)
    finally:
        rig.state_observer=None
        rig.message_observer=None
        rig._output=old_output
    for message in messages: old_output(message)
    if error: print('行程中止：%s'%error)
    final_x=int(rig.last_state[0]) if rig.last_state else None
    print('零速请求位置µm=%s；最终收到位置µm=%s；距目标µm=%s'%
          (stop_x,final_x,None if final_x is None else p.target_um-final_x))
    print('收到停稳证据' if confirmed else '停稳未确认；需现场确认停止')
    return 0 if confirmed and error is None else 1
