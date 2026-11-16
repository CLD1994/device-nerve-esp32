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
            self.assertAlmostEqual(p.budget_mm(0),50)
    def test_reserve_is_not_added_to_braking_budget(self):
        self.assertAlmostEqual(Plan(C,600,40,50).budget_mm(0),50)
    def test_shared_acceleration_changes_watchdog_braking(self):
        self.assertAlmostEqual(Plan(dict(C, ACC_MAX=10000),600,20,50).budget_mm(0),48)
        self.assertAlmostEqual(Plan(dict(C, ACC_MAX=5000),600,20,50).budget_mm(0),66)
        self.assertAlmostEqual(Plan(dict(C, ACC_MAX=10000),600,20,0).budget_mm(0),18)
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
        self.assertTrue(g.observe(347000,600))
    def test_guard_direction_and_soft_limit(self):
        for x,v in [(-3001,0),(417000,0),(0,1251)]:
            with self.assertRaises(RuntimeError): Guard(Plan(C,600,20,50),0).observe(x,v)
    def test_negative_remaining(self):
        self.assertTrue(Guard(Plan(C,-600,20,50),0).observe(-350000,-600))

if __name__ == '__main__': unittest.main()

class EndpointTest(unittest.TestCase):
    def test_left_reference_can_move_inward_only(self):
        self.assertFalse(Guard(Plan(C,600,20,50),-426970).observe(-426970,0))
        with self.assertRaises(ValueError): Guard(Plan(C,-600,20,50),-426970)
    def test_entered_latch_and_physical_range(self):
        g=Guard(Plan(C,600,20,50),-426970)
        g.observe(-416970,0)
        with self.assertRaises(RuntimeError): g.observe(-416971,0)
        with self.assertRaises(ValueError): Guard(Plan(C,600,20,50),-427471)
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
            def begin_stop_observation(self): pass
            def end_stop_observation(self): pass
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
                    x=350000 if self.t>.7 else 1000
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

class StartToleranceTest(unittest.TestCase):
    def test_both_endpoints_allow_192um_inward(self):
        for direction in (1,-1):
            p=Plan(C,600*direction,20,50)
            start=-direction*(p.physical_um+192)
            g=Guard(p,start,.5)
            self.assertFalse(g.observe(start,0))
            self.assertFalse(g.observe(start+direction*100,1*direction))
            g.observe(-direction*p.physical_um,1*direction)
            g.observe(-direction*(p.physical_um+1),0)
            g.observe(-direction*(p.physical_um-100),0)
            with self.assertRaises(RuntimeError):g.observe(-direction*(p.physical_um+1),0)
    def test_outside_noise_then_significant_reversal(self):
        p=Plan(C,600,20,50);g=Guard(p,-p.physical_um-192,.5)
        g.observe(-p.physical_um-100,0)
        self.assertFalse(g.observe(-p.physical_um-101,0))
        self.assertFalse(g.observe(-p.physical_um-200,0))
        with self.assertRaises(RuntimeError):g.observe(-p.physical_um-201,0)
    def test_bad_start_direction_and_tolerance(self):
        p=Plan(C,600,20,50)
        for start,tolerance in [(-p.physical_um-501,.5),(p.physical_um+192,.5),(-p.physical_um-1,0),(-p.physical_um,1.1),(-p.physical_um,float('nan'))]:
            with self.assertRaises(ValueError):Guard(p,start,tolerance)

class InitialToleranceChainTest(ExecutorTest):
    def test_initial_stillness_observes_entry_then_exit_no_nonzero(self):
        from travel_limit import run
        r,a,s=self.fixture(); original=r.poll_available
        def poll():
            observer=r.state_observer
            r.state_observer=None
            original()
            r.state_observer=observer
            if r.t<.42:x=-427162  # 192um超出左物理端
            elif r.t<.44:x=-426870
            else:x=-426971
            r.last_state=[str(x),'0','0','0']
            if observer:observer()
        r.poll_available=poll
        with self.assertRaises(RuntimeError):run(r,a,s)
        self.assertFalse(any(line.startswith('VEL ') and line!='VEL 0' for _,line in r.writes))

class DynamicNormalBudgetTest(unittest.TestCase):
    def test_watchdog_wait_is_separate_from_normal_trigger(self):
        p=Plan(dict(C,ACC_MAX=10000),600,20,50)
        self.assertAlmostEqual(p.budget_mm(0,0),48)
        self.assertAlmostEqual(p.watchdog_budget_mm(0,0),108)
        self.assertAlmostEqual(p.budget_mm(0,.02),60)
    def test_actual_speed_and_stale_age(self):
        p=Plan(dict(C,ACC_MAX=10000),600,20,50)
        self.assertAlmostEqual(p.budget_mm(800,.01),80)
        for age in (-.001,.101,float('nan')):
            with self.assertRaises(RuntimeError): p.budget_mm(0,age)
    def test_latest_age_changes_trigger_without_new_position(self):
        p=Plan(dict(C,ACC_MAX=10000),600,20,50)
        g=Guard(p,0)
        self.assertFalse(g.observe(340000,600,0))
        self.assertTrue(g.observe(340000,600,.02))

    def test_default_ten_ms_debug_assumption(self):
        p=Plan(dict(C,ACC_MAX=10000),600,20,10)
        self.assertAlmostEqual(p.budget_mm(0,0),24)
        self.assertAlmostEqual(p.watchdog_budget_mm(0,0),84)


class RecoveryNoiseTest(unittest.TestCase):
    def test_single_and_accumulated_outward_motion_both_directions(self):
        for d in (1,-1):
            p=Plan(C,600*d,20,10)
            start=-d*(p.physical_um+185)
            g=Guard(p,start,.5)
            self.assertFalse(g.observe(start-d,0))
            self.assertFalse(g.observe(start+d,0))
            for delta in range(1,100):g.observe(start-d*delta,0)
            with self.assertRaises(RuntimeError):g.observe(start-d*100,0)
            g=Guard(p,start,.5)
            with self.assertRaises(RuntimeError):g.observe(start-d*101,0)
    def test_absolute_tolerance_not_expanded_by_noise(self):
        p=Plan(C,600,20,10)
        g=Guard(p,-p.physical_um-490,.5)
        g.observe(-p.physical_um-500,0)
        with self.assertRaises(RuntimeError):g.observe(-p.physical_um-501,0)
    def test_large_inward_progress_does_not_allow_return_to_start(self):
        p=Plan(C,600,20,10)
        g=Guard(p,-p.physical_um-450,.5)
        g.observe(-p.physical_um-150,0)
        with self.assertRaises(RuntimeError):g.observe(-p.physical_um-251,0)

    def test_recovery_latches_at_100um_inside_not_first_crossing(self):
        for d in (1,-1):
            p=Plan(C,600*d,20,10)
            g=Guard(p,-d*(p.physical_um+185),.5)
            g.observe(-d*(p.physical_um-1),0)
            g.observe(-d*(p.physical_um+1),0)
            self.assertFalse(g.physical_entered)
            g.observe(-d*(p.physical_um-99),0)
            self.assertFalse(g.physical_entered)
            g.observe(-d*(p.physical_um-100),0)
            self.assertTrue(g.physical_entered)
            with self.assertRaises(RuntimeError):g.observe(-d*(p.physical_um+1),0)
    def test_inside_start_remains_strict(self):
        p=Plan(C,600,20,10)
        g=Guard(p,-p.physical_um,.5)
        with self.assertRaises(RuntimeError):g.observe(-p.physical_um-1,0)

class RecoveryRunTest(ExecutorTest):
    def test_initial_one_um_noise_can_start_and_complete(self):
        from travel_limit import run
        r,a,s=self.fixture();original=r.poll_available;frames=0
        def poll():
            nonlocal frames
            observer=r.state_observer
            r.state_observer=None
            original()
            r.state_observer=observer
            frames+=1
            if not any(line=='VEL 600' for _,line in r.writes):
                x=-C['CAL_LENGTH_UM']//2-185+(frames%2)
                r.last_state=[str(x),'0','0','0']
            if observer:observer()
        r.poll_available=poll
        self.assertEqual(run(r,a,s),0)
        self.assertTrue(any(line=='VEL 600' for _,line in r.writes))
        self.assertEqual(r.writes[-1][1],'VEL 0')

class TimingPhaseTest(ExecutorTest):
    def test_plan_only_marks_query_not_ready_stillness(self):
        from session_timing import SessionTiming
        from travel_limit import run
        r,a,s=self.fixture();a.plan=True;r.timing=SessionTiming(r._clock)
        self.assertEqual(run(r,a,s),0)
        self.assertIsNotNone(r.timing.report()['query_complete_s'])
        self.assertIsNone(r.timing.report()['preflight_complete_s'])
    def test_unconfirmed_initial_stillness_is_not_preflight_complete(self):
        from session_timing import SessionTiming
        from travel_limit import run
        r,a,s=self.fixture();r.timing=SessionTiming(r._clock);original=r.poll_available
        def poll():
            observer=r.state_observer;r.state_observer=None;original();r.state_observer=observer
            r.last_state=['0','0','1','0']
            if observer:observer()
        r.poll_available=poll
        with self.assertRaisesRegex(RuntimeError,'停稳'):run(r,a,s)
        self.assertIsNotNone(r.timing.report()['query_complete_s'])
        self.assertIsNone(r.timing.report()['preflight_complete_s'])

class StopHeartbeatRunTest(unittest.TestCase):
    def test_normal_run_waits_for_first_stop_heartbeat_then_succeeds(self):
        import cartpole_host
        from host_test_support import session
        from travel_limit import run
        from types import SimpleNamespace
        r,port,clock,_=session(cartpole_host.Rig)
        stop_polls=0
        def poll():
            nonlocal stop_polls
            r.replies.update(C)
            r.last_mode=('READY','NONE')
            zero=b'VEL 0\n' in port.writes
            moving=b'VEL 600\n' in port.writes and not zero
            x=380000 if moving and clock.value>.7 else 0
            vx=600 if moving else 0
            if zero:
                stop_polls+=1;x=380000
            heartbeat=b'' if zero and stop_polls<=3 else b'VEL_VALID 1 1\n'
            r._consume(heartbeat+('STATE %d 0 %d 0\n'%(x,vx)).encode())
        r.poll_available=poll
        a=SimpleNamespace(v=600,reserve_mm=20,inflight_ms=10,max_seconds=1,plan=False)
        self.assertEqual(run(r,a,clock.advance),0)
        self.assertGreater(stop_polls,3)
        self.assertFalse(r.velocity_validity.failed)
        self.assertEqual(port.writes[-1],b'VEL 0\n')
