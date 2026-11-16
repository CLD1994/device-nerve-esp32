"""主机单调时钟旁路观测；不请求命令、等待或认定物理加速度。"""

class SessionTiming:
    def __init__(self, clock):
        self.clock=clock
        self.started=clock()
        self.values={name:None for name in (
            'query_complete_s','preflight_complete_s','first_nonzero_attempt_s','last_nonzero_attempt_s',
            'first_nonzero_complete_s','last_nonzero_complete_s','first_nonzero_vx_received_s',
            'first_zero_attempt_s','first_zero_complete_s','stop_observed_s','command_elapsed_s',
            'target_95_received_s')}
        self.acceleration_peak=None
        self.acceleration_peak_at=None
        self.latest_velocity=None
        self.target_velocity=None
        self.samples=0
        self.peak=None
        self.attempts=self.completions=0

    def mark(self,name):
        self.values[name+'_s']=self.clock()-self.started

    def write_attempt(self,velocity):
        at=self.clock()-self.started
        if velocity:
            self.attempts+=1
            if self.values['first_nonzero_attempt_s'] is None:
                self.values['first_nonzero_attempt_s']=at
                self.target_velocity=velocity
            self.values['last_nonzero_attempt_s']=at
        elif self.values['first_zero_attempt_s'] is None:self.values['first_zero_attempt_s']=at

    def write_complete(self,velocity):
        at=self.clock()-self.started
        if velocity:
            self.completions+=1
            if self.values['first_nonzero_complete_s'] is None:self.values['first_nonzero_complete_s']=at
            self.values['last_nonzero_complete_s']=at
        elif self.values['first_zero_complete_s'] is None:self.values['first_zero_complete_s']=at

    def state(self,velocity):
        if self.values['first_nonzero_attempt_s'] is None:return
        if (self.values['first_nonzero_complete_s'] is not None
                and self.values['first_zero_attempt_s'] is None
                and velocity*self.target_velocity > 0
                and (self.acceleration_peak is None or abs(velocity)>abs(self.acceleration_peak))):
            self.acceleration_peak=velocity
            self.acceleration_peak_at=self.clock()-self.started
        if (self.values['target_95_received_s'] is None
                and self.values['first_nonzero_complete_s'] is not None
                and self.values['first_zero_attempt_s'] is None
                and velocity*self.target_velocity > 0
                and abs(velocity)*100 >= abs(self.target_velocity)*95):
            self.values['target_95_received_s']=self.clock()-self.started
        self.samples+=1
        self.peak=max(abs(velocity),self.peak or 0)
        if velocity and self.values['first_nonzero_vx_received_s'] is None:
            self.values['first_nonzero_vx_received_s']=self.clock()-self.started

    def finish(self, latest_velocity=None):
        self.latest_velocity=latest_velocity
        self.values['command_elapsed_s']=self.clock()-self.started

    def report(self):
        r=dict(self.values)
        r['command_start_monotonic_s']=self.started
        r['acceleration_peak_velocity_mm_s']=self.acceleration_peak
        r['acceleration_peak_interval_s']=(None if self.acceleration_peak_at is None else
            self.acceleration_peak_at-self.values['first_nonzero_attempt_s'])
        r['latest_valid_velocity_mm_s']=self.latest_velocity
        r['target_velocity_mm_s']=self.target_velocity
        r['target_95_threshold_mm_s']=None if self.target_velocity is None else abs(self.target_velocity)*.95
        def difference(end,start):
            return None if r[end] is None or r[start] is None else r[end]-r[start]
        r.update(target_95_interval_s=difference('target_95_received_s','first_nonzero_attempt_s'),
                 nonzero_write_attempts=self.attempts,nonzero_write_completions=self.completions,
                 received_state_samples=self.samples,peak_abs_received_vx_mm_s=self.peak,
                 nonzero_attempt_span_s=difference('last_nonzero_attempt_s','first_nonzero_attempt_s'),
                 received_response_interval_s=difference('first_nonzero_vx_received_s','first_nonzero_attempt_s'),
                 zero_to_stop_observed_s=difference('stop_observed_s','first_zero_attempt_s'))
        return r

    def summary(self):
        r=self.report()
        def seconds(key,missing='未发生'):
            return missing if r[key] is None else '%.3f s'%r[key]
        def interval(key):
            return '未确认' if r[key] is None else '%.1f ms'%(r[key]*1000)
        peak='未观测' if r['peak_abs_received_vx_mm_s'] is None else '%d mm/s'%r['peak_abs_received_vx_mm_s']
        if r['target_velocity_mm_s'] is None:
            target='目标95%达速估计：无非零目标'
        else:
            outcome=('未确认完整非零写入' if r['first_nonzero_complete_s'] is None else
                     '未观测到达成' if r['target_95_interval_s'] is None else
                     '%.1f ms（接收估计）'%(r['target_95_interval_s']*1000))
            target='目标%d mm/s，同向95%%门槛（速度绝对值）%g mm/s：%s'%(r['target_velocity_mm_s'],r['target_95_threshold_mm_s'],outcome)
            if r['target_95_interval_s'] is None:
                target+=('；加速阶段同向峰值未观测' if self.acceleration_peak is None else
                         '；加速阶段同向峰值%d mm/s，首次达到耗时%.1f ms（接收估计）'%(
                             self.acceleration_peak,r['acceleration_peak_interval_s']*1000))
        latest='未确认' if self.latest_velocity is None else '%d mm/s（最后收到值）'%self.latest_velocity
        return '\n'.join([
            '主机计时：总耗时 %s；以下时点均为命令入口后。'%seconds('command_elapsed_s','未确认'),
            target+'。',
            '查询完成 %s；预检完成 %s。'%(seconds('query_complete_s'),seconds('preflight_complete_s')),
            '非零写入尝试：首 %s / 末 %s；完整返回：首 %s / 末 %s。'%(
                seconds('first_nonzero_attempt_s'),seconds('last_nonzero_attempt_s'),
                seconds('first_nonzero_complete_s'),seconds('last_nonzero_complete_s')),
            '首次收到非零速度 %s；首次零速请求 %s / 完整返回 %s；观测停稳 %s。'%(
                seconds('first_nonzero_vx_received_s','未观测'),seconds('first_zero_attempt_s'),
                seconds('first_zero_complete_s'),seconds('stop_observed_s','未确认')),
            '时间间隔：首末非零尝试 %s；首尝试至非零速度接收 %s；零速请求至观测停稳 %s。'%(
                interval('nonzero_attempt_span_s'),interval('received_response_interval_s'),interval('zero_to_stop_observed_s')),
            '非零写入：尝试 %d 次 / 完整返回 %d 次；接收速度样本 %d 个，绝对峰值 %s；结束最新速度 %s。'%(
                r['nonzero_write_attempts'],r['nonzero_write_completions'],r['received_state_samples'],peak,latest),
            '完整写入不代表设备收讫；接收速度含延迟、滤波和噪声，不证明机械起停或准确加速度。'])
