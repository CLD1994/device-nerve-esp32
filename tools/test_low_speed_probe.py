import types
import unittest
from low_speed_probe import Link, Abort, execute, motion, validate, stopped


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
        data=self.rx+('STATE %d 3141592 %d 0\n'%(self.x,self.v)).encode();self.rx=b'';return data


def args(command='run', confirm=True):
    return types.SimpleNamespace(command=command,confirm_motion=confirm,velocity=20,acceleration=100,hold=.5)


class Tests(unittest.TestCase):
    def setup_link(self, fake=None):
        f=fake or Fake(); return f,Link(f,f.clock,f.sleep)
    def test_plan_readonly(self):
        f,l=self.setup_link();execute(l,args('plan'))
        self.assertEqual(f.writes,['QUERY','CALIB?','CONFIG?'])
    def test_explicit_confirmation(self):
        f,l=self.setup_link()
        with self.assertRaises(Abort):execute(l,args(confirm=False))
        self.assertFalse(any(s.startswith(('VEL ','CONFIG ')) for s in f.writes))
    def test_single_direction_bounded_and_stops(self):
        f,l=self.setup_link();execute(l,args())
        self.assertIn('CONFIG ACC_MAX 100',f.writes)
        self.assertNotIn('CONFIG ACC_MAX 5000',f.writes)
        self.assertNotIn('ENABLE',f.writes)
        self.assertTrue(all(s in ('VEL 0','VEL 20') for s in f.writes if s.startswith('VEL ')))
        self.assertEqual(f.writes[-1],'VEL 0');self.assertLess(f.t,2)
    def test_malformed_aborts_before_motion(self):
        f,l=self.setup_link();f.rx+=b'BROKEN\n'
        with self.assertRaises(Abort):execute(l,args())
        self.assertNotIn('VEL 20',f.writes)
    def test_motion_failure_zero(self):
        class Broken(Fake):
            def read(self,n):
                if self.v: self.rx+=b'BAD\n'
                return super().read(n)
        f,l=self.setup_link(Broken())
        with self.assertRaises(Abort):execute(l,args())
        self.assertEqual(f.v,0)
    def test_short_write(self):
        f,l=self.setup_link(); f.write=lambda data:0
        with self.assertRaises(Abort):l.send('QUERY')
    def test_guards_and_faults_stop(self):
        for injection in ('STATE -4000 0 20 0\n','STATE 31000 0 20 0\n','MODE FAULT POWER\n'):
            class Unsafe(Fake):
                def read(self,n):
                    if self.v:
                        self.rx += injection.encode()
                        data=self.rx; self.rx=b''; return data
                    return super().read(n)
            f,l=self.setup_link(Unsafe())
            with self.assertRaises(Abort): execute(l,args())
            self.assertEqual(f.v,0)
    def test_ctrl_c_stops(self):
        class Interrupted(Fake):
            def read(self,n):
                if self.v: raise KeyboardInterrupt()
                return super().read(n)
        f,l=self.setup_link(Interrupted())
        with self.assertRaises(KeyboardInterrupt): execute(l,args())
        self.assertEqual(f.v,0)
    def test_no_new_states_stops(self):
        class Silent(Fake):
            def read(self,n):
                return b'' if self.v else super().read(n)
        f,l=self.setup_link(Silent())
        with self.assertRaises(Abort): execute(l,args())
        self.assertEqual(f.v,0)
    def test_bad_config_never_moves(self):
        class Reject(Fake):
            def write(self,data):
                n=super().write(data)
                if data.startswith(b'CONFIG ACC_MAX '):
                    self.rx=self.rx.replace(b'OK ACC_MAX 100',b'OK ACC_MAX 5000')
                return n
        f,l=self.setup_link(Reject())
        with self.assertRaises(Abort):execute(l,args())
        self.assertNotIn('VEL 20',f.writes)
    def test_not_enabled_never_moves(self):
        class Disabled(Fake):
            def read(self,n):return super().read(n).replace(b'MODE READY NONE',b'MODE DISABLED NONE')
        f,l=self.setup_link(Disabled())
        with self.assertRaises(Abort):execute(l,args())
        self.assertNotIn('VEL 20',f.writes)
        self.assertNotIn('ENABLE',f.writes)
    def test_persistent_drift_not_stopped(self):
        for speed in (1,9):
            class Drift(Fake):
                def read(self,n):
                    self.x=self.t*speed*1000
                    self.rx+=('STATE %d 0 %d 0\n'%(self.x,speed)).encode()
                    data=self.rx;self.rx=b'';return data
            f,l=self.setup_link(Drift());l.mode=('READY','NONE')
            with self.assertRaises(Abort):stopped(l)
            self.assertGreaterEqual(f.t,1)
    def test_stationary_needs_elapsed_time(self):
        f,l=self.setup_link();l.mode=('READY','NONE');stopped(l)
        self.assertGreaterEqual(f.t,.2)
    def test_batch_motion_cannot_be_hidden(self):
        class Batch(Fake):
            def read(self,n):
                return b'\nSTATE 0 0 9 0\nSTATE 0 0 0 0\n'
        f,l=self.setup_link(Batch());l.mode=('READY','NONE')
        with self.assertRaises(Abort):stopped(l)
    def test_stop_phase_violation_latches(self):
        class AfterStop(Fake):
            moved=False
            def write(self,data):
                if data==b'VEL 20\n': self.moved=True
                if data==b'VEL 0\n' and self.moved:
                    self.rx+=b'STATE 32000 0 0 0\nSTATE 10000 0 0 0\n'
                return super().write(data)
        f,l=self.setup_link(AfterStop())
        with self.assertRaises(Abort):execute(l,args())
        self.assertIsNotNone(l.guard_failure)
        self.assertEqual(f.v,0)
    def test_limits(self):
        for k,v in [('velocity',0),('velocity',21),('acceleration',5000),('hold',float('nan')),('hold',1)]:
            a=args();setattr(a,k,v)
            with self.assertRaises(ValueError):validate(a)
    def test_deadline_when_not_reaching(self):
        class Slow(Fake):
            def read(self,n):
                data=super().read(n)
                return data.replace(b' 20 0\n',b' 1 0\n')
        f,l=self.setup_link(Slow())
        with self.assertRaisesRegex(Abort,'窗口'):execute(l,args())
        self.assertEqual(f.v,0);self.assertLess(f.t,2)

if __name__=='__main__': unittest.main()
