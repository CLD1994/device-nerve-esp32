"""小车调试测量；不构造摆角、不改变模型双路测量或固件故障保护。"""
from cart_stream import parse_cart_state


class CartValidity:
    def __init__(self, clock):
        self.clock=clock;self.active=False;self.failed=False
        self.received_at=None;self.frame=None;self.valid=False
        self.device_us=None;self.seq=None;self.sample_us=None
    def age(self):
        if self.frame is None or self.received_at is None:return None
        return (self.clock()-self.received_at)+(self.frame['device_us']-self.frame['sample_us'])/1e6
    def ready(self):
        age=self.age()
        good=self.valid and age is not None and 0<=age<=.1
        if self.active and not good:self.failed=True
        return good and not self.failed
    def require(self):
        if not self.ready():
            raise RuntimeError('小车独立测量缺失、无效、过期或已中止；需新固件开启 CONFIG_TELEMETRY_CART_DIAGNOSTICS，禁止退回旧 STATE')
    def command(self,line):
        p=line.split()
        if p and (p[0]=='ENABLE' or (p[0]=='VEL' and p[1:]!=['0'])):
            self.require();self.active=True
    def update(self, frame):
        if self.active:self.ready()  # 晚到数据不能掩盖过期。
        if self.device_us is not None and frame['device_us']<self.device_us:
            self.failed=True;raise ValueError('设备时间倒退或设备重启')
        self.device_us=frame['device_us']
        if not frame['valid']:
            self.valid=False
            if self.active:self.failed=True
            return False
        if self.seq is not None:
            if frame['seq']<self.seq or frame['sample_us']<self.sample_us:
                self.failed=True;raise ValueError('小车采样身份倒退')
            if frame['seq']==self.seq:
                if any(frame[k]!=self.frame[k] for k in ('sample_us','x_um','vx_mm_s')):
                    self.failed=True;raise ValueError('相同采样序列的内容矛盾')
                return False  # 重复样本不能续新鲜度/停稳窗，也不能恢复无效。
            if frame['sample_us']<=self.sample_us:
                self.failed=True;raise ValueError('采样时间未随序列推进')
        self.seq=frame['seq'];self.sample_us=frame['sample_us']
        self.frame=frame;self.received_at=self.clock();self.valid=True
        return self.ready()


class CartMotionMixin:
    """仅vel命令使用；通用Rig和模型仍坚持双路门禁。"""
    cart_period_s=.020
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.velocity_validity=CartValidity(self._clock)
        self.last_cart=None;self.pole_valid=None;self.pole_changes=0;self.pole_invalid_seen=False
    def cart_diagnostic_summary(self):
        return ('摆杆测量：本会话%s无效报告；有效性状态记录 %d 次（含首次）；'
                'vel只依赖小车独立观测，固件 MT6835 故障仍中止。' %
                ('收到过' if self.pole_invalid_seen else '未收到',self.pole_changes))
    def motion_cart(self):
        if self.last_cart is None:raise RuntimeError('小车独立测量缺失；需启用 CONFIG_TELEMETRY_CART_DIAGNOSTICS')
        return self.last_cart['x_um'],self.last_cart['vx_mm_s']
    def motion_age(self):
        gate=self.stop_observation or self.velocity_validity
        age=gate.age()
        if age is None:raise RuntimeError('小车测量时间未知')
        return age
    def state_is_fresh(self,max_age=.1):
        gate=self.stop_observation or self.velocity_validity
        age=gate.age()
        return self.last_cart is not None and gate.valid and age is not None and 0<=age<=max_age
    def note_velocity_gate(self):
        if self.velocity_validity.failed:self.note_failure('existing_failure_latch')
        elif not self.state_is_fresh():self.note_failure('cart_measurement_missing_or_expired')
    def begin_stop_observation(self):
        old=self.stop_observation or self.velocity_validity
        self.stop_observation=CartValidity(self._clock)
        # 停车重新收证，但旧/重复的采样不能被当作新样本。
        self.stop_observation.seq=old.seq
        self.stop_observation.sample_us=old.sample_us
        self.stop_observation.frame=old.frame
        self.stop_observation.device_us=old.device_us
        self.last_cart=None;self.state_received_at=None
    def _invalidate_stop_observation(self):
        if self.stop_observation is not None:self.begin_stop_observation()
    def _unknown(self,line):
        self.unknown_count+=1
        self.last_cart=None
        if self.velocity_validity.active or self.stop_observation is not None:
            self.note_failure('unknown_line',current_raw=True)
            self.velocity_validity.failed=True
            if self.stop_observation is not None:
                self._invalidate_stop_observation()
                raise RuntimeError('停车观测收到未知或损坏数据')
        else:self._output('[UNKNOWN] %r'%line)
    def _dispatch(self,line):
        p=line.split()
        if p[:1]==['CART_STATE1']:
            gate=self.stop_observation or self.velocity_validity
            try:
                frame=parse_cart_state(line)
                fresh=gate.update(frame)
            except ValueError as exc:
                self.note_failure('invalid_cart_measurement',current_raw=True)
                self.velocity_validity.failed=True;self.last_cart=None
                raise RuntimeError(str(exc)) from exc
            if not frame['valid']:
                self.last_cart=None;self.state_received_at=None
                self.note_failure('cart_measurement_invalid',current_raw=True)
                if self.stop_observation is not None:raise RuntimeError('停车观测小车测量无效')
            if not fresh and (gate.failed or not gate.valid):
                self.last_cart=None;self.state_received_at=None
            if fresh:
                self.last_cart=frame;self.state_received_at=gate.received_at
                if self.timing is not None:self.timing.state(frame['vx_mm_s'])
                if self.state_observer is not None:self.state_observer()
            return
        if p[:1]==['VEL_VALID']:
            if len(p)!=3 or any(x not in ('0','1') for x in p[1:]):
                self._unknown(line);return
            pole=p[2]=='1'
            if pole!=self.pole_valid:
                self.pole_valid=pole
                self.pole_changes=min(self.pole_changes+1,2**64-1)
                self.pole_invalid_seen=self.pole_invalid_seen or not pole
            if p[1]=='0':
                gate=self.stop_observation or self.velocity_validity
                gate.valid=False;self.last_cart=None
                self.note_failure('cart_measurement_invalid',current_raw=True)
                if gate.active:self.velocity_validity.failed=True
                if self.stop_observation is not None:raise RuntimeError('停车观测小车测量无效')
            return
        if p[:1]==['STATE']:
            # 只保存真实四维帧供检查，不刷新小车运动门禁/时间/观测回调。
            try:
                if len(p)!=5:raise ValueError()
                values=[int(x) for x in p[1:]]
                if any(not -2**31<=x<2**31 for x in values):raise ValueError()
            except ValueError:self._unknown(line);return
            self.last_state=p[1:];self.state_count+=1;return
        super()._dispatch(line)
        if p[:1]==['MODE'] and self.velocity_validity.active and p!=['MODE','READY','NONE']:
            self.note_failure('firmware_mode_changed',current_raw=True)
            self.velocity_validity.failed=True
