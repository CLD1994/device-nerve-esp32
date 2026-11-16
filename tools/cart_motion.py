"""vel使用统一STATE的小车lane，模型/其它Rig继续要求完整双路。"""
from velocity_validity import VelocityValidity

class CartMotionMixin:
    cart_period_s=.002  # 名义500Hz相位预算，不是最大调度延迟保证。
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.velocity_validity=VelocityValidity(self._clock,required_mask=1)
        self.last_cart=None;self.pole_valid=None;self.pole_changes=0;self.pole_invalid_seen=False
    def cart_diagnostic_summary(self):
        return ('摆杆测量：本会话%s无效报告；有效性状态记录 %d 次（含首次）；'
                'vel只依赖小车lane，固件 MT6835 故障仍中止。'%
                ('收到过' if self.pole_invalid_seen else '未收到',self.pole_changes))
    def motion_cart(self):
        if self.last_cart is None:raise RuntimeError('统一STATE小车测量缺失；请同步新固件及工具')
        return self.last_cart['x_um'],self.last_cart['vx_mm_s']
    def motion_age(self):
        age=(self.stop_observation or self.velocity_validity).age()
        if age is None:raise RuntimeError('小车测量时间未知')
        return age
    def state_is_fresh(self,max_age=.1):
        gate=self.stop_observation or self.velocity_validity
        age=gate.age()
        return self.last_cart is not None and gate.flags is not None and gate.flags[0]==1 and age is not None and 0<=age<=max_age
    def clear_motion_state(self):
        super().clear_motion_state();self.last_cart=None
    def on_measurement_frame(self,frame):
        pole=bool(frame['flags']&2)
        if pole!=self.pole_valid:
            self.pole_valid=pole;self.pole_changes=min(self.pole_changes+1,2**64-1)
            self.pole_invalid_seen=self.pole_invalid_seen or not pole
    def accept_measurement_frame(self,frame):
        self.last_cart=frame['cart']
        # 不以无效摆杆构造四维状态。
        if frame['pole'] is not None:
            c,p=frame['cart'],frame['pole']
            self.last_state=[str(c['x_um']),str(p['theta_urad']),str(c['vx_mm_s']),str(p['vth_mrad_s'])]
        else:self.last_state=None
        self.state_received_at=(self.stop_observation or self.velocity_validity).received_at
        self.state_count+=1
        if self.timing is not None:self.timing.state(self.last_cart['vx_mm_s'])
        if self.state_observer is not None:self.state_observer()
    def _unknown(self,line):
        try:super()._unknown(line)
        finally:self.last_cart=None
