"""运动探针的串口与时钟替身；通过 Link 的构造参数注入。

模拟命令回执与位置变化，不代替真实电机动力学或停车验证。
"""

class Fake:
    def __init__(self):
        self.t = 0.; self.writes = []; self.rx = b'\n'; self.v = 0; self.x = 0
    def clock(self): return self.t
    def sleep(self, n): self.t += n; self.x += self.v * n * 1000
    def write(self, data):
        cmd=data.decode().strip(); self.writes.append(cmd)
        if cmd=='QUERY': self.rx+=b'MODE READY NONE\n'
        elif cmd=='CALIB?':
            self.rx+=b'OK CAL_STATE 2\nOK CAL_LENGTH_UM 853436\nOK CAL_SAVED 1\nOK CAL_STORAGE 0\n'
        elif cmd=='CONFIG?':
            for k,v in dict(VEL_MAX=20,ACC_MAX=100,WDT_MS=100,WDT_DEC=100,X_MARGIN_UM=10000,POLE_ZERO_URAD=2159697,POLE_INV=1,X_INV=0,STEP_LOSS_UM=3000).items():
                self.rx+=('OK %s %s\n'%(k,v)).encode()
        elif cmd.startswith('CONFIG '):
            _,k,v=cmd.split(); self.rx+=('OK %s %s\n'%(k,v)).encode()
        elif cmd.startswith('VEL '): self.v=int(cmd.split()[1])
        return len(data)
    def read(self,n):
        data=self.rx+b'VEL_VALID 1 1\n'+('STATE %d 3141592 %d 0\n'%(self.x,self.v)).encode();self.rx=b'';return data


class Rig(Fake):
    def __init__(self):
        super().__init__(); self.cfg=dict(VEL_MAX=20,ACC_MAX=100,WDT_MS=100,WDT_DEC=100,X_MARGIN_UM=10000,POLE_ZERO_URAD=0,POLE_INV=1,X_INV=0,STEP_LOSS_UM=3000)
    def write(self,data):
        cmd=data.decode().strip()
        if cmd=='CONFIG?':
            self.writes.append(cmd)
            self.rx+=''.join('OK %s %d\n'%p for p in self.cfg.items()).encode();return len(data)
        if cmd.startswith('CONFIG '):
            _,k,v=cmd.split();self.cfg[k]=int(v)
        return super().write(data)


class Bench(Rig):
    def __init__(self):
        super().__init__(); self.x=-326662
    def write(self,data):
        n=super().write(data)
        self.rx=self.rx.replace(b'853436',b'853325')
        return n
