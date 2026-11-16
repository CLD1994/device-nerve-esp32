"""行程规划单元测试，不连接设备。"""
import unittest
from travel_limit import Plan, Guard

C = dict(CAL_STATE=2, CAL_SAVED=1, CAL_STORAGE=0, CAL_LENGTH_UM=853940,
         VEL_MAX=1250, ACC_MAX=9000, WDT_MS=100, X_MARGIN_UM=10000)

class PlannerTest(unittest.TestCase):
    def test_positive_and_negative(self):
        for velocity in (600, -600):
            p = Plan(C, velocity, 20, 50)
            self.assertEqual(p.target_um, (1 if velocity > 0 else -1)*396970)
            self.assertAlmostEqual(p.budget_mm(0),170)
    def test_reserve_is_not_added_to_braking_budget(self):
        self.assertAlmostEqual(Plan(C,600,40,50).budget_mm(0),170)
    def test_shared_acceleration_changes_watchdog_braking(self):
        self.assertAlmostEqual(Plan(dict(C, ACC_MAX=10000),600,20,50).budget_mm(0),168)
        self.assertAlmostEqual(Plan(dict(C, ACC_MAX=5000),600,20,50).budget_mm(0),186)
        self.assertAlmostEqual(Plan(dict(C, ACC_MAX=10000),600,20,0).budget_mm(0),138)
    def test_invalid_configuration(self):
        for key,value in [('CAL_STATE',3),('CAL_SAVED',0),('CAL_STORAGE',1),('ACC_MAX',0),('CAL_LENGTH_UM',0)]:
            with self.subTest(key=key), self.assertRaises(ValueError): Plan(dict(C,**{key:value}),600,20,50)
    def test_old_firmware_rejected(self):
        with self.assertRaisesRegex(ValueError, 'WDT_DEC'):
            Plan(dict(C,WDT_DEC=5000),600,20,50)
    def test_invalid_request(self):
        for v,reserve,lag in [(0,20,50),(1300,20,50),(600,-1,50),(600,500,50),(600,20,float('nan'))]:
            with self.assertRaises(ValueError): Plan(C,v,reserve,lag)
    def test_guard_brakes_before_target(self):
        g=Guard(Plan(C,600,20,50),0)
        self.assertFalse(g.observe(0,0))
        self.assertTrue(g.observe(227000,600))
    def test_guard_direction_and_soft_limit(self):
        for x,v in [(-3001,0),(417000,0),(0,1251)]:
            with self.assertRaises(RuntimeError): Guard(Plan(C,600,20,50),0).observe(x,v)
    def test_negative_remaining(self):
        self.assertTrue(Guard(Plan(C,-600,20,50),0).observe(-300000,-600))

if __name__ == '__main__': unittest.main()

class EndpointTest(unittest.TestCase):
    def test_left_reference_can_move_inward_only(self):
        self.assertFalse(Guard(Plan(C,600,20,50),-426970).observe(-426970,0))
        with self.assertRaises(ValueError): Guard(Plan(C,-600,20,50),-426970)
    def test_entered_latch_and_physical_range(self):
        g=Guard(Plan(C,600,20,50),-426970)
        g.observe(-416970,0)
        with self.assertRaises(RuntimeError): g.observe(-416971,0)
        with self.assertRaises(ValueError): Guard(Plan(C,600,20,50),-426971)
    def test_short_watchdog_rejected(self):
        with self.assertRaises(ValueError): Plan(dict(C,WDT_MS=20),600,20,50)

class ExecutorTest(unittest.TestCase):
    def fixture(self, mode='normal'):
        from types import SimpleNamespace
        from velocity_validity import VelocityValidity
        class Fake:
            def __init__(self):
                self.t=0.; self.state_received_at=0.; self.last_reply=None; self.replies={}; self.last_mode=None; self.last_state=['0','0','0','0']; self.state_observer=None
                self.writes=[]; self._output=lambda x: None
                self.velocity_validity=VelocityValidity(self._clock)
            def _clock(self): return self.t
            def state_is_fresh(self): return mode!='stale' or self.t<.65
            def send_line(self,line):
                self.velocity_validity.command(line)
                self.writes.append((self.t,line))
                if mode=='slowwrite' and line=='VEL 600': self.t+=.06
            def poll_available(self):
                self.state_received_at=self.t
                self.replies.update(C); self.last_mode=('READY','NONE')
                self.velocity_validity.update(['VEL_VALID','1','1'])
                moving=any(s=='VEL 600' for _,s in self.writes)
                zero=bool(self.writes and self.writes[-1][1]=='VEL 0')
                if moving and not zero:
                    x=280000 if self.t>.7 else 1000
                    if mode=='reverse': x=-4000
                    if mode=='timeout': x=1000
                    self.last_state=[str(x),'0','600','0']
                else: self.last_state=[self.last_state[0],'0','0','0']
                if self.state_observer: self.state_observer()
        r=Fake()
        args=SimpleNamespace(v=600,reserve_mm=20,inflight_ms=50,max_seconds=.5,plan=False)
        return r,args,lambda dt:setattr(r,'t',r.t+dt)
    def test_success_and_command_spacing(self):
        from travel_limit import run
        r,a,s=self.fixture(); self.assertEqual(run(r,a,s),0)
        commands=[t for t,l in r.writes if l=='VEL 600']
        self.assertTrue(commands)
        self.assertTrue(all(y-x>=.02-1e-9 for x,y in zip(commands,commands[1:])))
        self.assertEqual(r.writes[-1][1],'VEL 0')
    def test_failures_stop_without_resume(self):
        from travel_limit import run
        for mode in ('reverse','timeout','stale','slowwrite'):
            r,a,s=self.fixture(mode)
            with self.subTest(mode=mode):
                self.assertEqual(run(r,a,s),1)
                self.assertEqual(r.writes[-1][1],'VEL 0')
                self.assertTrue(r.velocity_validity.failed)
    def test_old_firmware_sends_no_motion(self):
        from travel_limit import run
        r,a,s=self.fixture()
        original=r.poll_available
        def old_poll():
            original()
            r.replies['WDT_DEC']=5000
        r.poll_available=old_poll
        with self.assertRaisesRegex(ValueError, 'WDT_DEC'):run(r,a,s)
        self.assertEqual([line for _,line in r.writes],['CALIB?','CONFIG?','QUERY'])
    def test_plan_read_only(self):
        from travel_limit import run
        r,a,s=self.fixture();a.plan=True
        self.assertEqual(run(r,a,s),0)
        self.assertEqual([l for _,l in r.writes],['CALIB?','CONFIG?','QUERY'])

class StillnessTest(unittest.TestCase):
    def test_intermediate_motion_resets_batch(self):
        from types import SimpleNamespace
        from travel_limit import Stillness
        r=SimpleNamespace(t=0,last_state=['0','0','0','0']);r._clock=lambda:r.t
        s=Stillness(r);s.observe()
        r.t=.19;r.last_state=['0','0','1','0'];s.observe()
        r.t=.21;r.last_state=['0','0','0','0'];s.observe()
        self.assertFalse(s.confirmed)
        for t in (.28,.35,.42): r.t=t;s.observe()
        self.assertTrue(s.confirmed)
    def test_position_range_not_only_latest_zero_velocity(self):
        from types import SimpleNamespace
        from travel_limit import Stillness
        r=SimpleNamespace(t=0,last_state=['0','0','0','0']);r._clock=lambda:r.t
        s=Stillness(r);s.observe()
        r.t=.19;r.last_state=['101','0','0','0'];s.observe()
        r.t=.21;r.last_state=['0','0','0','0'];s.observe()
        self.assertFalse(s.confirmed)

class StickyFailureTest(ExecutorTest):
    def test_stop_receive_failure_stays_failed(self):
        from travel_limit import run
        r,a,s=self.fixture(); original=r.poll_available
        injected=False
        def poll():
            nonlocal injected
            if not injected and any(line=='VEL 0' for _,line in r.writes):
                injected=True
                raise RuntimeError('stop receive failure')
            original()
        r.poll_available=poll
        self.assertEqual(run(r,a,s),1)
        self.assertTrue(r.velocity_validity.failed)
    def test_intermediate_stop_protocol_error_cannot_be_overwritten(self):
        from travel_limit import run
        for bad,good in [('ERR BUSY','OK VEL 0'),('MODE FAULT STEP_LOSS','MODE READY NONE')]:
            r,a,s=self.fixture(); original=r.poll_available
            injected=False
            def poll():
                nonlocal injected
                if not injected and any(line=='VEL 0' for _,line in r.writes):
                    injected=True
                    r.message_observer(bad)
                    r.message_observer(good)
                original()
            r.poll_available=poll
            with self.subTest(bad=bad):
                self.assertEqual(run(r,a,s),1)
                self.assertTrue(r.velocity_validity.failed)
