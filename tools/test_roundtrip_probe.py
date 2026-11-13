import unittest
from types import SimpleNamespace
from low_speed_probe import Link,Abort
from test_step50k_probe import Bench as BaseBench

class Bench(BaseBench):
    def __init__(self):
        super().__init__();self.x=-413000
from roundtrip_probe import execute

def args(command='run'):
    return SimpleNamespace(command=command,confirm_motion=True,confirm_clearance=True,accept_stopping_risk=True)

class Tests(unittest.TestCase):
    def test_plan_queries_only(self):
        f=Bench();l=Link(f,f.clock,f.sleep);execute(l,args('plan'))
        self.assertEqual(f.writes,['QUERY','CALIB?','CONFIG?'])
    def test_four_directions_with_stops_and_approaches(self):
        f=Bench();l=Link(f,f.clock,f.sleep);execute(l,args())
        starts=[e['value']['direction'] for e in l.events if e['direction']=='segment_start']
        self.assertEqual(starts,[1,-1,1,-1])
        ends=[e['value'] for e in l.events if e['direction']=='segment_stopped']
        self.assertEqual(len(ends),4)
        self.assertTrue(all(0<e['remaining_um']<=5000 for e in ends))
        self.assertEqual(f.v,0);self.assertNotIn('ENABLE',f.writes);self.assertNotIn('RESET',f.writes)
        self.assertEqual(f.cfg['ACC_MAX'],10000);self.assertEqual(f.cfg['WDT_DEC'],5000)
        self.assertIn('VEL -1250',f.writes);self.assertIn('VEL -20',f.writes)
    def test_fault_cancels_remaining_and_approach(self):
        class Fault(Bench):
            def read(self,n):
                if self.v:self.rx+=b'MODE FAULT STEP_LOSS\n'
                return super().read(n)
        f=Fault();l=Link(f,f.clock,f.sleep)
        with self.assertRaises(Abort):execute(l,args())
        self.assertNotIn('VEL -1250',f.writes);self.assertNotIn('VEL 20',f.writes);self.assertEqual(f.v,0)
    def test_existing_fault_never_moves(self):
        class Fault(Bench):
            def read(self,n):return super().read(n).replace(b'MODE READY NONE',b'MODE FAULT STEP_LOSS')
        f=Fault();l=Link(f,f.clock,f.sleep)
        with self.assertRaises(Abort):execute(l,args())
        self.assertFalse(any(c.startswith('VEL ') for c in f.writes))
    def test_missing_risk_confirmation_refuses(self):
        f=Bench();l=Link(f,f.clock,f.sleep);a=args();a.accept_stopping_risk=False
        with self.assertRaises(Abort):execute(l,a)
        self.assertFalse(any(c.startswith('VEL ') for c in f.writes))
    def test_approach_invalid_cancels_reverse(self):
        class Invalid(Bench):
            def read(self,n):
                if self.v==20:self.rx+=b'VEL_VALID 0 1\n'
                return super().read(n)
        f=Invalid();l=Link(f,f.clock,f.sleep)
        with self.assertRaises(Abort):execute(l,args())
        self.assertNotIn('VEL -1250',f.writes);self.assertEqual(f.v,0)

    def test_late_read_cancels_remaining(self):
        class Late(Bench):
            delayed=False
            def read(self,n):
                if self.v and not self.delayed:self.t+=.051;self.delayed=True
                return super().read(n)
        f=Late();l=Link(f,f.clock,f.sleep)
        with self.assertRaises(Abort):execute(l,args())
        self.assertEqual(f.writes.count('VEL 1250'),1)
        self.assertNotIn('VEL -1250',f.writes);self.assertEqual(f.v,0)
    def test_approach_boundary_abort(self):
        class Cross(Bench):
            def read(self,n):
                if self.v==100:self.x=417000
                return super().read(n)
        f=Cross();l=Link(f,f.clock,f.sleep)
        with self.assertRaises(Abort):execute(l,args())
        self.assertNotIn('VEL -1250',f.writes);self.assertEqual(f.v,0)

if __name__=='__main__':unittest.main()
