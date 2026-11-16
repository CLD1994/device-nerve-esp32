"""原子STATE的独立有效性/样本身份；设备钟只作差分，不与主机绝对钟相减。"""
import time

class VelocityValidity:
    def __init__(self, clock=time.monotonic, required_mask=3):
        self.clock=clock;self.required_mask=required_mask
        self.flags=None;self.received_at=None;self.active=False;self.failed=False
        self.frame=None;self.new_sample=False;self.seen={};self.committed={}
        self.boot=None;self.tick=None;self.device_elapsed=0
        self.sample_times={}  # integer microseconds relative to first device tick; may start negative
        self.host_baseline=None;self.minimum_offset=0.;self.relative_backlog_s=0.
        self.source_age_s=0.
    def fail(self,message):
        self.failed=True
        raise RuntimeError(message)
    def age(self):
        if self.received_at is None:return None
        return self.source_age_s+self.clock()-self.received_at+self.relative_backlog_s
    def ready(self):
        age=self.age()
        flags=0 if self.flags is None else self.flags[0]+2*self.flags[1]
        good=(flags&self.required_mask)==self.required_mask and age is not None and 0<=age<=.1
        if self.active and not good:self.failed=True
        return good and not self.failed
    def update(self, frame):
        if not isinstance(frame,dict):self.fail('需要新统一 STATE；旧 VEL_VALID 不再支持')
        self.new_sample=False
        if self.active:self.ready()  # 晚到帧不能掩盖已过期的活动会话。
        now=self.clock()
        if self.boot is None:
            self.boot=frame['boot'];self.tick=frame['tick'];self.host_baseline=now
        elif frame['boot']!=self.boot:
            self.fail('STATE启动身份变化；需要结束并重新建立会话')
        else:
            delta=(frame['tick']-self.tick)&0xffffffff
            if delta>=0x80000000:self.fail('STATE设备时钟倒退或断流超过半区间')
            if delta==0:
                if self.frame is not None and frame!=self.frame:self.fail('相同设备时刻的STATE内容矛盾')
                self.ready();return False
            self.tick=frame['tick'];self.device_elapsed+=delta
            offset=now-self.host_baseline-self.device_elapsed/1e6
            self.minimum_offset=min(self.minimum_offset,offset)
            self.relative_backlog_s=max(0.,offset-self.minimum_offset)
        self.flags=(frame['flags']&1,(frame['flags']>>1)&1)
        self.frame=frame
        all_new=True;ages=[]
        for bit,name in ((1,'cart'),(2,'pole')):
            if not self.required_mask&bit:continue
            lane=frame[name]
            if lane is None:
                all_new=False
                if self.active:self.failed=True
                continue
            sample_time=self.device_elapsed-lane['age_us']
            old=self.seen.get(name)
            if old is not None:
                delta=(lane['seq']-old['seq'])&0xffff
                if delta>=0x8000:self.fail('STATE %s样本序号倒退或断流超过半区间'%name)
                previous_time=self.sample_times[name]
                if (delta==0 and sample_time!=previous_time) or (delta!=0 and sample_time<=previous_time):
                    self.fail('STATE %s样本序号与采样时间矛盾'%name)
                if delta==0 and any(lane[k]!=old[k] for k in lane if k!='age_us'):
                    self.fail('STATE重复样本的测量值矛盾')
            self.seen[name]=lane
            self.sample_times[name]=sample_time
            if self.committed.get(name)==lane['seq']:all_new=False
            ages.append(lane['age_us']/1e6)
        if all_new:
            self.received_at=now;self.source_age_s=max(ages)
            self.committed={name:frame[name]['seq'] for bit,name in ((1,'cart'),(2,'pole')) if self.required_mask&bit}
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
        """仅停车新收证，保留原门禁失败和身份水位，不恢复非零。"""
        out=VelocityValidity(self.clock,self.required_mask)
        for key in ('boot','tick','device_elapsed','host_baseline','minimum_offset','relative_backlog_s'):
            setattr(out,key,getattr(self,key))
        out.sample_times=dict(self.sample_times)
        out.seen=dict(self.seen);out.committed=dict(self.committed);out.frame=self.frame
        return out
