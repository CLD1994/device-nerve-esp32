"""主机单调时钟旁路观测；不请求命令、等待或认定物理加速度。"""
import json

class SessionTiming:
    def __init__(self, clock):
        self.clock=clock
        self.started=clock()
        self.values={name:None for name in (
            'query_complete_s','preflight_complete_s','first_nonzero_attempt_s','last_nonzero_attempt_s',
            'first_nonzero_complete_s','last_nonzero_complete_s','first_nonzero_vx_received_s',
            'first_zero_attempt_s','first_zero_complete_s','stop_observed_s','command_elapsed_s')}
        self.samples=0
        self.peak=None
        self.attempts=self.completions=0

    def mark(self,name):
        self.values[name+'_s']=self.clock()-self.started

    def write_attempt(self,velocity):
        at=self.clock()-self.started
        if velocity:
            self.attempts+=1
            if self.values['first_nonzero_attempt_s'] is None:self.values['first_nonzero_attempt_s']=at
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
        self.samples+=1
        self.peak=max(abs(velocity),self.peak or 0)
        if velocity and self.values['first_nonzero_vx_received_s'] is None:
            self.values['first_nonzero_vx_received_s']=self.clock()-self.started

    def finish(self):
        self.values['command_elapsed_s']=self.clock()-self.started

    def report(self):
        r=dict(self.values)
        r['command_start_monotonic_s']=self.started
        def difference(end,start):
            return None if r[end] is None or r[start] is None else r[end]-r[start]
        r.update(nonzero_write_attempts=self.attempts,nonzero_write_completions=self.completions,
                 received_state_samples=self.samples,peak_abs_received_vx_mm_s=self.peak,
                 nonzero_attempt_span_s=difference('last_nonzero_attempt_s','first_nonzero_attempt_s'),
                 received_response_interval_s=difference('first_nonzero_vx_received_s','first_nonzero_attempt_s'),
                 zero_to_stop_observed_s=difference('stop_observed_s','first_zero_attempt_s'))
        return r

    def summary(self):
        return ('主机计时（相对cmd_vel入口秒；null=未发生/未确认；写入完成不代表固件收讫；'
                '接收速度含延迟/滤波/噪声，不证明真实起停或准确加速度）：\n'
                +json.dumps(self.report(),ensure_ascii=False,allow_nan=False))
