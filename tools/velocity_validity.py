"""STATE有效位与主机接收时效；不能识别设备重复样本、重启或排队延迟。"""
import time

class VelocityValidity:
    def __init__(self, clock=time.monotonic, required_mask=3):
        self.clock=clock;self.required_mask=required_mask
        self.flags=None;self.received_at=None;self.active=False;self.failed=False
        self.frame=None;self.new_sample=False
    def fail(self,message):
        self.failed=True
        raise RuntimeError(message)
    def age(self):
        if self.received_at is None:return None
        return self.clock()-self.received_at
    def ready(self):
        age=self.age()
        flags=0 if self.flags is None else self.flags[0]+2*self.flags[1]
        good=(flags&self.required_mask)==self.required_mask and age is not None and 0<=age<=.1
        if self.active and not good:self.failed=True
        return good and not self.failed
    def update(self, frame):
        if not isinstance(frame,dict):self.fail('需要统一 STATE；旧 VEL_VALID 不再支持')
        self.new_sample=False
        if self.active:self.ready()  # 晚到帧不能掩盖已过期的活动会话。
        self.flags=(frame['flags']&1,(frame['flags']>>1)&1)
        self.frame=frame
        if frame['flags']&self.required_mask==self.required_mask:
            self.received_at=self.clock()
            # 每帧是新收到的观测，不代表设备产生了不同的采样。
            self.new_sample=self.ready()
        else:self.ready()
        return self.new_sample
    def require(self):
        if not self.ready():raise RuntimeError('统一STATE所需测量缺失、无效、过期或已中止；禁止继续运动')
    def command(self,line):
        p=line.split()
        if p and (p[0]=='ENABLE' or (p[0]=='VEL' and p[1:]!=['0'])):
            self.require();self.active=True
    def stopped_copy(self):
        """独立停车收证，原运动门禁失败不清除，不恢复非零。"""
        return VelocityValidity(self.clock,self.required_mask)
