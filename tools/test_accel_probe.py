import unittest
from types import SimpleNamespace
from test_low_speed_probe import Fake
from accel_probe import execute, Link, Abort

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

def args(cmd='run',yes=True):return SimpleNamespace(command=cmd,confirm_motion=yes,confirm_clearance=yes)
class Tests(unittest.TestCase):
    def run_probe(self,f=None,a=None):
        f=f or Rig();l=Link(f,f.clock,f.sleep);execute(l,a or args());return f,l
    def test_plan_no_writes(self):
        f,l=self.run_probe(a=args('plan'));self.assertEqual(f.writes,['QUERY','CALIB?','CONFIG?'])
    def test_no_permission(self):
        f=Rig()
        with self.assertRaises(Abort):self.run_probe(f,args(yes=False))
        self.assertFalse(any(x.startswith('VEL') for x in f.writes))
    def test_run_fixed(self):
        f,l=self.run_probe();self.assertIn('VEL 400',f.writes);self.assertEqual(f.v,0)
        self.assertEqual(f.cfg['WDT_DEC'],5000);self.assertNotIn('ENABLE',f.writes)
        self.assertTrue(any(x['direction']=='result' for x in l.events))
    def test_clearance_reject(self):
        f=Rig();f.x=180000
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertNotIn('VEL 400',f.writes)
    def test_guard_continues_read(self):
        class Unsafe(Rig):
            danger=False; after=0
            def read(self,n):
                if self.v:self.danger=True
                if self.danger:
                    self.after+=1;self.x=101000
                return super().read(n)
        f=Unsafe()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertGreater(f.after,3);self.assertEqual(f.v,0)
    def test_power_fault(self):
        class Fault(Rig):
            def read(self,n):
                if self.v:self.rx+=b'MODE FAULT POWER\n'
                return super().read(n)
        f=Fault()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertEqual(f.v,0);self.assertNotIn('RESET',f.writes)
    def test_ramp_and_deadline(self):
        class Ramp(Rig):
            def __init__(self):
                super().__init__();self.target=0;self.sent=[]
            def write(self,data):
                old=self.v;n=super().write(data)
                if data.startswith(b'VEL '):
                    self.target=int(data.split()[1]);self.v=old
                    self.sent.append((self.t,self.target))
                return n
            def sleep(self,n):
                old=self.v;step=self.cfg['ACC_MAX']*n
                self.v+=max(-step,min(step,self.target-self.v))
                self.t+=n;self.x+=(old+self.v)/2*n*1000
        f=Ramp();self.run_probe(f)
        self.assertGreater(f.x,60000);self.assertLess(f.x,85000)
        nonzero=[t for t,v in f.sent if v]
        self.assertLessEqual(nonzero[-1]-nonzero[0],.23)

    def test_write_time_counts_and_never_reaching(self):
        class Slow(Rig):
            def __init__(self):super().__init__();self.sent=[]
            def write(self,data):
                if data==b'VEL 400\n':
                    self.sent.append(self.t);self.t+=.02
                return super().write(data)
            def read(self,n):
                return super().read(n).replace(b' 400 0\n',b' 100 0\n')
        f=Slow()
        with self.assertRaisesRegex(Abort,'窗口'):self.run_probe(f)
        self.assertLessEqual(f.sent[-1]-f.sent[0],.23)
        self.assertEqual(f.v,0)

    def test_missing_state_after_start(self):
        class Silent(Rig):
            def read(self,n):return b'' if self.v else super().read(n)
        f=Silent()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertEqual(f.v,0)

    def test_latched_batch_severe(self):
        class Batch(Rig):
            def read(self,n):
                if self.v:self.rx+=b'STATE 201000 0 400 0\nSTATE 0 0 400 0\n'
                return super().read(n)
        f=Batch()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertEqual(f.v,0)

    def test_config_readback_failure(self):
        class Changed(Rig):
            def write(self,data):
                n=super().write(data)
                if data==b'CONFIG WDT_DEC 5000\n':self.cfg['WDT_DEC']=100
                return n
        f=Changed()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertNotIn('VEL 400',f.writes)

    def test_ctrl_c_no_reenable(self):
        class Interrupt(Rig):
            def read(self,n):
                if self.v:raise KeyboardInterrupt()
                return super().read(n)
        f=Interrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_probe(f)
        self.assertEqual(f.v,0)

    def test_write_failure_stops(self):
        class Broken(Rig):
            def write(self,data):
                if data==b'VEL 400\n':raise OSError('write timeout')
                return super().write(data)
        f=Broken()
        with self.assertRaises(OSError):self.run_probe(f)
        self.assertEqual(f.writes[-1],'VEL 0')

    def test_position_jump_cannot_be_hidden(self):
        class Jump(Rig):
            def read(self,n):
                if self.v:self.rx+=b'STATE 5000 0 400 0\nSTATE 0 0 400 0\n'
                return super().read(n)
        f=Jump()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertEqual(f.v,0)

    def test_console_not_in_motion_or_stop(self):
        from unittest.mock import patch
        class Danger(Rig):
            def read(self,n):
                if self.v:self.rx+=b'STATE 201000 0 400 0\n'
                return super().read(n)
        f=Danger();unsafe=[]
        def console(*a,**kw):
            if f.v:unsafe.append(a);f.t+=1
        with patch('builtins.print',console):
            with self.assertRaises(Abort):self.run_probe(f)
        self.assertEqual(unsafe,[])

    def test_normal_500hz_empty_polls_are_not_fault(self):
        class Paced(Rig):
            last_read=-1
            def read(self,n):
                if not self.rx and self.t-self.last_read < .002:return b''
                self.last_read=self.t
                return super().read(n)
        f=Paced();self.run_probe(f)
        self.assertIn('VEL 400',f.writes)

    def test_late_fresh_frame_cannot_resume_after_heartbeat_deadline(self):
        class Gap(Rig):
            def __init__(self):super().__init__();self.jumped=False;self.nonzero=0
            def write(self,data):
                if data==b'VEL 400\n':self.nonzero+=1
                return super().write(data)
            def read(self,n):
                if self.v and not self.jumped:
                    self.t+=.08;self.jumped=True
                return super().read(n)
        f=Gap()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertEqual(f.nonzero,1);self.assertEqual(f.v,0)

    def test_short_gap_waits_without_duplicate_nonzero(self):
        class Gap(Rig):
            def __init__(self):super().__init__();self.first=None;self.sent=[]
            def write(self,data):
                if data==b'VEL 400\n':
                    self.sent.append(self.t)
                    if self.first is None:self.first=self.t
                return super().write(data)
            def read(self,n):
                if self.v and self.first is not None and  .024 <= self.t-self.first < .028:return b''
                return super().read(n)
        f=Gap();self.run_probe(f)
        self.assertGreaterEqual(f.sent[1]-f.sent[0],.025)
        self.assertLess(f.sent[1]-f.sent[0],.05)

    def test_stream_ends_before_first_motion_no_nonzero(self):
        class Ends(Rig):
            frozen=False
            def read(self,n):
                if self.frozen:return b''
                data=super().read(n)
                if self.t>=.4:self.frozen=True
                return data
        f=Ends()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertNotIn('VEL 400',f.writes)
        self.assertLess(f.t,1.6)

if __name__=='__main__':unittest.main()
