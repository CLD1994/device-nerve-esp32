import unittest
from host_test_support import session, receive
from cartpole_host import CartRig, Rig

class CartMotionTests(unittest.TestCase):
    def test_pole_invalid_does_not_stop_cart_or_fake_state(self):
        r,p,c,out=session(CartRig)
        receive(r,p,'MODE READY NONE','CART_STATE1 10000 9000 1 1 10 0')
        r.send_line('VEL 900')
        receive(r,p,'VEL_VALID 1 0','CART_STATE1 30000 29000 2 1 20 10')
        r.send_line('VEL 900')
        self.assertEqual(r.motion_cart(),(20,10));self.assertIsNone(r.last_state)
        self.assertTrue(r.pole_invalid_seen);self.assertIn('收到过',r.cart_diagnostic_summary())
    def test_pole_fault_still_stops(self):
        r,p,_,_=session(CartRig)
        receive(r,p,'MODE READY NONE','CART_STATE1 10000 9000 1 1 10 0');r.send_line('VEL 9')
        with self.assertRaises(RuntimeError):receive(r,p,'MODE FAULT MT6835')
        with self.assertRaises(RuntimeError):r.send_line('VEL 9')
        r.send_line('VEL 0')
    def test_old_state_cannot_enable_new_vel(self):
        r,p,_,_=session(CartRig);receive(r,p,'VEL_VALID 1 1','STATE 1 2 0 0')
        with self.assertRaisesRegex(RuntimeError,'CONFIG_TELEMETRY_CART_DIAGNOSTICS'):r.send_line('VEL 9')
    def test_model_rig_remains_two_channel(self):
        r,p,_,_=session(Rig);receive(r,p,'VEL_VALID 1 1','STATE 1 2 0 0');r.send_line('VEL 9')
        with self.assertRaises(RuntimeError):receive(r,p,'VEL_VALID 1 0')
    def test_duplicate_does_not_refresh_or_observe(self):
        r,p,c,_=session(CartRig);receive(r,p,'CART_STATE1 10000 9000 1 1 10 0')
        old=r.state_received_at;events=[];r.state_observer=lambda:events.append(1)
        c.advance(.05);receive(r,p,'CART_STATE1 60000 9000 1 1 10 0')
        self.assertEqual(r.state_received_at,old);self.assertFalse(events)
    def test_sequence_backward_invalid_cart_and_corruption_fail(self):
        for line in ('CART_STATE1 30000 29000 0 1 10 0','CART_STATE1 30000 0','CART_STATE1 x','VEL_VALID 1 7','alien'):
            with self.subTest(line=line):
                r,p,_,_=session(CartRig);receive(r,p,'CART_STATE1 10000 9000 1 1 10 0');r.send_line('VEL 9')
                with self.assertRaises(RuntimeError):receive(r,p,line)
    def test_stop_uses_new_cart_without_clearing_failed(self):
        r,p,_,_=session(CartRig);receive(r,p,'CART_STATE1 10000 9000 1 1 10 0');r.send_line('VEL 9')
        with self.assertRaises(RuntimeError):receive(r,p,'CART_STATE1 20000 0')
        r.send_line('VEL 0');r.begin_stop_observation()
        receive(r,p,'VEL_VALID 1 0','CART_STATE1 30000 29000 2 1 20 0')
        self.assertTrue(r.state_is_fresh());self.assertTrue(r.velocity_validity.failed)
        with self.assertRaises(RuntimeError):r.send_line('VEL 9')
    def test_age_includes_device_interval_not_epoch_difference(self):
        r,p,c,_=session(CartRig);receive(r,p,'CART_STATE1 9000000000 8999990000 1 1 10 0')
        self.assertAlmostEqual(r.motion_age(),.01+c()-r.state_received_at)
        c.advance(.091);self.assertFalse(r.state_is_fresh())

class CartMoreTests(unittest.TestCase):
    def test_stop_repeat_old_sample_does_not_confirm(self):
        r,p,c,_=session(CartRig);receive(r,p,'CART_STATE1 10000 9000 1 1 10 0')
        r.send_line('VEL 9');r.send_line('VEL 0');r.begin_stop_observation()
        receive(r,p,'CART_STATE1 20000 9000 1 1 10 0')
        self.assertFalse(r.state_is_fresh());self.assertIsNone(r.last_cart)
    def test_stop_malformed_resets_only_observation_and_can_recover(self):
        r,p,c,_=session(CartRig);receive(r,p,'CART_STATE1 10000 9000 1 1 10 0')
        r.send_line('VEL 9');r.send_line('VEL 0');r.begin_stop_observation()
        with self.assertRaises(RuntimeError):receive(r,p,'broken')
        receive(r,p,'CART_STATE1 30000 29000 2 1 10 0')
        self.assertTrue(r.state_is_fresh());self.assertTrue(r.velocity_validity.failed)
    def test_late_frame_cannot_restore_motion(self):
        r,p,c,_=session(CartRig);receive(r,p,'CART_STATE1 10000 9000 1 1 10 0');r.send_line('VEL 9')
        c.advance(.101)
        with self.assertRaises(RuntimeError):receive(r,p,'CART_STATE1 130000 129000 2 1 10 0')
        self.assertIsNone(r.last_cart)
    def test_normal_rig_ignores_valid_cart_but_rejects_malformed(self):
        r,p,c,_=session(Rig);receive(r,p,'VEL_VALID 1 1','STATE 1 2 0 0');r.send_line('VEL 9')
        stamp=r.state_received_at
        receive(r,p,'CART_STATE1 10000 9000 1 1 100 50')
        self.assertEqual(r.state_received_at,stamp);self.assertEqual(r.last_state,['1','2','0','0'])
        with self.assertRaises(RuntimeError):receive(r,p,'CART_STATE1 bad')
    def test_normal_budget_has_phase_floor_without_double_age(self):
        from travel_limit import Plan
        from test_travel_limit import C
        p=Plan(dict(C,ACC_MAX=10000),1000,20,10,.020)
        self.assertEqual(p.budget_mm(900,0),80)
        self.assertEqual(p.budget_mm(900,.015),80)
        self.assertAlmostEqual(p.budget_mm(900,.030),90)
        self.assertEqual(p.watchdog_budget_mm(900,0),180)


class CartBytePathTests(unittest.TestCase):
    def build(self):
        from host_test_support import ManualClock
        from test_travel_limit import C
        clock=ManualClock()
        class Port:
            timeout=.2
            def __init__(self):self.buffer=b'opening\n';self.writes=[];self.seq=0;self.emitted=-1;self.moving=False;self.started=None;self.x=0
            def factory(self,*a,**kw):return self
            def produce(self):
                if clock()-self.emitted>=.02:
                    self.emitted=clock();self.seq+=1
                    if self.moving and clock()-self.started>.1:self.x=375000
                    stamp=int(clock()*1e6)
                    self.buffer+=('VEL_VALID 1 0\nCART_STATE1 %d %d %d 1 %d %d\n'%(stamp,stamp,self.seq,self.x,600 if self.moving else 0)).encode()
            @property
            def in_waiting(self):self.produce();return len(self.buffer)
            def read(self,n):
                clock.advance(.001);self.produce();data=self.buffer[:n];self.buffer=self.buffer[n:];return data
            def write(self,data):
                self.writes.append(data);line=data.decode().strip()
                if line in ('CALIB?','CONFIG?'):self.buffer+=''.join('OK %s %d\n'%(k,v) for k,v in C.items()).encode()
                if line=='QUERY':self.buffer+=b'MODE READY NONE\n'
                if line=='VEL 600':
                    if self.started is None:self.started=clock()
                    self.moving=True
                if line=='VEL 0':self.moving=False
                return len(data)
            def close(self):pass
        p=Port();r=CartRig('memory',serial_factory=p.factory,clock=clock,output=lambda s:None)
        return r,p,clock
    def test_full_single_trip_works_without_any_state_or_pole_valid(self):
        from types import SimpleNamespace
        from travel_limit import run
        r,p,c=self.build()
        a=SimpleNamespace(v=600,reserve_mm=20,inflight_ms=10,max_seconds=2,plan=False,start_tolerance_mm=.5)
        self.assertEqual(run(r,a,sleep=c.advance),0)
        self.assertIn(b'VEL 600\n',p.writes);self.assertEqual(p.writes[-1],b'VEL 0\n')
        self.assertIsNone(r.last_state);self.assertEqual(r.motion_cart(),(375000,0))
    def test_hold_uses_cart_and_retains_normal_watchdog_exit(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from cartpole_host import cmd_vel
        r,p,c=self.build()
        with patch('cartpole_host.time.time',c):self.assertEqual(cmd_vel(r,SimpleNamespace(v=600,hold=.2)),0)
        self.assertIn(b'VEL 600\n',p.writes);self.assertNotIn(b'VEL 0\n',p.writes)

if __name__=='__main__':unittest.main()
