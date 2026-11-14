import unittest
from types import SimpleNamespace
from probe_test_support import Bench, Rig
from probe_link import Link, Abort
from step50k_probe import execute


def options(**kw):
    d=dict(command='run',acceleration=9000,hold_s=0.,margin_mm=50.,normal_decel=9000,watchdog_decel=5000,
           watchdog_ms=100,inflight_ms=20.,window_s=.3,
           normal_decel_evidence='现场记录编号A',watchdog_decel_evidence='现场记录编号B',
           inflight_evidence='延迟预算记录C',confirm_motion=True,confirm_clearance=True)
    d.update(kw);return SimpleNamespace(**d)

class ProbeTests(unittest.TestCase):
    def run_probe(self,f=None,a=None):
        f=f or Bench(); link=Link(f,f.clock,f.sleep)
        execute(link,a or options());return f,link
    def test_selected_acceleration_ack_and_budget(self):
        f,l=self.run_probe(a=options(acceleration=30000))
        self.assertIn('CONFIG ACC_MAX 30000',f.writes)
        self.assertEqual(f.cfg['ACC_MAX'],30000)
        self.assertEqual(f.cfg['WDT_DEC'],5000)
        b=next(e['value'] for e in l.events if e['direction']=='plan')
        self.assertAlmostEqual(b['ramp_s'],1250/30000)
        self.assertEqual(b['inputs']['acceleration'],30000)
    def test_selected_acceleration_ack_mismatch_refuses_motion(self):
        class Wrong(Bench):
            def write(self,data):
                n=super().write(data)
                if data.startswith(b'CONFIG ACC_MAX 30000'):
                    self.rx=self.rx.replace(b'OK ACC_MAX 30000',b'OK ACC_MAX 9000')
                return n
        f=Wrong()
        with self.assertRaisesRegex(Abort,'配置回执不匹配'):
            self.run_probe(f,options(acceleration=30000))
        self.assertNotIn('VEL 1250',f.writes)
    def test_invalid_acceleration_rejects_writes(self):
        for value in (99,30001,9000.5):
            f=Bench()
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.run_probe(f,options(acceleration=value))
            self.assertFalse(any(c.startswith(('CONFIG ','VEL ')) for c in f.writes))
    def test_normal_decel_above_selected_acceleration_rejected(self):
        f=Bench()
        with self.assertRaises(Abort):self.run_probe(f,options(acceleration=5000))
        self.assertNotIn('VEL 1250',f.writes)

    def test_fault_budget_cannot_be_relaxed(self):
        from step50k_probe import validate_run, stop_reserve_mm, budget_for
        f=Bench();l=Link(f,f.clock,f.sleep);l.state=(-326662,0,0,0)
        a=options(acceleration=11000,hold_s=.3,window_s=.5,margin_mm=100,
                  normal_decel=5000,inflight_ms=50)
        b=budget_for(l,a,{'CAL_LENGTH_UM':853325},{'X_MARGIN_UM':10000})
        self.assertFalse(b['conditional_fault_budget_fits'])
        with self.assertRaises(Abort):validate_run(a,b)
        self.assertEqual(stop_reserve_mm(a),443.75)

    def test_hold_resets_on_report_below_threshold(self):
        class Dip(Bench):
            first=None;dipped=None
            def write(self,data):
                if data==b'VEL 1250\n' and self.first is None:self.first=self.t
                return super().write(data)
            def read(self,n):
                data=super().read(n)
                if self.v and self.first is not None and self.t-self.first>=.05 and self.dipped is None:
                    self.dipped=self.t
                    data=data.replace(b' 1250 0\n',b' 1200 0\n')
                return data
        f=Dip();a=options(hold_s=.1,window_s=.3)
        _,l=self.run_probe(f,a)
        stop_tx=next(e['t'] for e in l.events if e['direction']=='tx' and e['value']=='VEL 0' and e['t']>f.first)
        self.assertGreaterEqual(stop_tx-f.dipped,.1)
        end=next(e['value'] for e in l.events if e['direction']=='motion_end')
        self.assertEqual(end['reason'],'approx_target_hold_completed')

    def test_plan_only_queries(self):
        f,l=self.run_probe(a=options(command='plan',hold_s=None,watchdog_decel=None))
        self.assertEqual(f.writes,['QUERY','CALIB?','CONFIG?'])
    def test_missing_inputs_reject_before_any_configuration(self):
        for key in ('hold_s','margin_mm','normal_decel','watchdog_decel','inflight_ms','window_s','normal_decel_evidence','watchdog_decel_evidence','inflight_evidence'):
            f=Bench()
            with self.subTest(key=key),self.assertRaises(Abort): self.run_probe(f,options(**{key:None}))
            self.assertFalse(any(s.startswith(('CONFIG ','VEL ')) for s in f.writes))
    def test_once_positive_and_stops_no_enable(self):
        f,l=self.run_probe()
        self.assertIn('VEL 1250',f.writes);self.assertEqual(f.v,0)
        self.assertNotIn('ENABLE',f.writes);self.assertNotIn('RESET',f.writes)
        self.assertEqual(f.cfg['ACC_MAX'],9000)
        self.assertEqual(f.cfg['WDT_DEC'],5000)
        self.assertTrue(any(e['direction']=='result' for e in l.events))
    def test_distance_rejection(self):
        f=Bench();f.x=0
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertNotIn('VEL 1250',f.writes)
    def test_invalid_does_not_resume(self):
        class Bad(Bench):
            def read(self,n):
                if self.v:self.rx+=b'VEL_VALID 0 1\nVEL_VALID 1 1\n'
                return super().read(n)
        f=Bad()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertEqual(f.writes.count('VEL 1250'),1);self.assertEqual(f.v,0)
    def test_silence_after_motion_is_bounded(self):
        class Quiet(Bench):
            active=False
            def read(self,n):
                self.active |= self.v!=0
                return b'' if self.active else super().read(n)
        f=Quiet()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertLess(f.t,3);self.assertEqual(f.v,0)
    def test_overspeed_aborts(self):
        class Fast(Bench):
            def read(self,n):
                if self.v:self.rx+=b'STATE -326662 0 1251 0\n'
                return super().read(n)
        f=Fast()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertEqual(f.v,0)
    def test_configuration_mismatch_rejects_before_nonzero(self):
        class Wrong(Bench):
            def write(self,data):
                result=super().write(data)
                if data.startswith(b'CONFIG ACC_MAX'):self.rx=self.rx.replace(b'OK ACC_MAX 9000',b'OK ACC_MAX 8000')
                return result
        f=Wrong()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertNotIn('VEL 1250',f.writes);self.assertEqual(f.v,0)
    def test_fault_does_not_reset_or_resume(self):
        class Fault(Bench):
            def read(self,n):
                if self.v:self.rx+=b'MODE FAULT POWER\n'
                return super().read(n)
        f=Fault()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertNotIn('RESET',f.writes);self.assertEqual(f.v,0)
    def test_forward_boundary_cannot_be_hidden_by_next_frame(self):
        class Jump(Bench):
            def read(self,n):
                if self.v:self.rx+=b'STATE 100000 0 1250 0\nSTATE -300000 0 1250 0\n'
                return super().read(n)
        f=Jump()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertEqual(f.writes.count('VEL 1250'),1)
    def test_never_reaches_target_hits_absolute_deadline(self):
        class Slow(Bench):
            def read(self,n):
                data=super().read(n)
                return data.replace(b' 1250 0\n',b' 1000 0\n')
        f=Slow()
        _,l=self.run_probe(f)
        end=next(e['value'] for e in l.events if e['direction']=='motion_end')
        self.assertEqual(end['reason'],'window_elapsed')
        self.assertFalse(end['approx_target_reached'])
        self.assertEqual(f.v,0);self.assertLess(f.t,3)
    def test_approximate_target_uses_two_percent_lower_bound(self):
        for speed in (1225,1233):
            class Near(Bench):
                def read(self,n):
                    return super().read(n).replace(b' 1250 0\n',(' %d 0\n'%speed).encode())
            f,l=self.run_probe(Near())
            end=next(e['value'] for e in l.events if e['direction']=='motion_end')
            self.assertEqual(end['reason'],'approx_target_hold_completed')
            self.assertTrue(end['approx_target_reached'])
            self.assertEqual(end['threshold_mm_s'],1225)
            self.assertEqual(f.v,0)
    def test_below_approximate_threshold_is_not_target_completion(self):
        class Near(Bench):
            def read(self,n):
                return super().read(n).replace(b' 1250 0\n',b' 1224 0\n')
        _,l=self.run_probe(Near())
        end=next(e['value'] for e in l.events if e['direction']=='motion_end')
        self.assertEqual(end['reason'],'window_elapsed')
        self.assertFalse(end['approx_target_reached'])
    def test_late_read_cannot_resume_motion(self):
        class Delayed(Bench):
            seen=False
            def read(self,n):
                if self.v and not self.seen:self.seen=True;self.t+=.051
                return super().read(n)
        f=Delayed()
        with self.assertRaisesRegex(Abort,'50ms续发截止'):self.run_probe(f)
        self.assertEqual(f.writes.count('VEL 1250'),1)
    def test_missing_permission_rejects_writes(self):
        f=Bench()
        with self.assertRaises(Abort):self.run_probe(f,options(confirm_motion=False))
        self.assertFalse(any(s.startswith(('VEL ','CONFIG ')) for s in f.writes))
    def test_disabled_is_not_automatically_enabled(self):
        class Disabled(Bench):
            def read(self,n):return super().read(n).replace(b'MODE READY NONE',b'MODE DISABLED NONE')
        f=Disabled()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertFalse(any(s.startswith(('ENABLE','VEL ','CONFIG ')) for s in f.writes))
    def test_exact_track_mismatch_rejects_plan(self):
        f=Rig();f.x=-326662
        with self.assertRaises(Abort):self.run_probe(f,options(command='plan'))
        self.assertNotIn('VEL 1250',f.writes)
    def test_short_write_cannot_report_complete(self):
        class Short(Bench):
            def write(self,data):
                if data==b'VEL 1250\n':return 2
                return super().write(data)
        f=Short()
        with self.assertRaises(Abort):self.run_probe(f)
        self.assertEqual(f.v,0)
    def test_watchdog_shorter_than_supported_cadence_rejected(self):
        for timeout in (10,25,50,99):
            f=Bench()
            with self.subTest(timeout=timeout),self.assertRaises(Abort):
                self.run_probe(f,options(watchdog_ms=timeout))
            self.assertFalse(any(s.startswith(('VEL ','CONFIG ')) for s in f.writes))
    def test_fifo_delayed_velocity_cannot_be_reported_stopped_before_arrival(self):
        class DelayedFIFO(Bench):
            def __init__(self):
                super().__init__();self.queue=[];self.first=None;self.delayed=False
            def write(self,data):
                command=data.decode().strip()
                if command.startswith('VEL ') and (command!='VEL 0' or self.first is not None):
                    if self.first is None:self.first=self.t
                    self.writes.append(command);self.queue.append((self.t+.280,int(command.split()[1])))
                    return len(data)
                return super().write(data)
            def read(self,n):
                if self.first is not None and not self.delayed:
                    self.t+=.051;self.delayed=True
                while self.queue and self.queue[0][0]<=self.t:
                    _,self.v=self.queue.pop(0)
                return super().read(n)
        f=DelayedFIFO();link=Link(f,f.clock,f.sleep)
        with self.assertRaises(Abort):execute(link,options(hold_s=0,margin_mm=1,watchdog_decel=9000,
                                                        inflight_ms=280,window_s=.139))
        stops=[event for event in link.events if event['direction']=='stop']
        self.assertTrue(stops)
        self.assertGreaterEqual(stops[-1]['t'],f.first+.280+.2)
        self.assertEqual(f.v,0)
        self.assertFalse(any(v!=0 for _,v in f.queue))
    def test_normal_window_includes_inflight_even_when_watchdog_is_stronger(self):
        from step50k_plan import calculate
        from step50k_probe import validate_run
        a=options(hold_s=0,margin_mm=10,normal_decel=2500,watchdog_decel=9000,
                  watchdog_ms=100,inflight_ms=200,window_s=.2)
        budget=calculate(hold_s=0,normal_decel=2500,watchdog_decel=9000,
                         watchdog_ms=100,inflight_ms=200,window_s=.2,margin_mm=10,
                         start_from_left_mm=100)
        with self.assertRaises(Abort):validate_run(a,budget)
    def test_dynamic_reserve_includes_inflight_on_normal_branch(self):
        from step50k_probe import stop_reserve_mm
        a=options(margin_mm=10,normal_decel=2500,watchdog_decel=9000,inflight_ms=200)
        self.assertAlmostEqual(stop_reserve_mm(a),572.5)
    def test_evidence_is_logged_verbatim_as_unverified_declaration(self):
        a=options(normal_decel_evidence='A：9000 ±误差',watchdog_decel_evidence='B\n复测',inflight_evidence='C 未做硬件认证')
        f,link=self.run_probe(a=a)
        record=next(e['value'] for e in link.events if e['direction']=='operator_declaration')
        self.assertFalse(record['independently_verified'])
        for key in ('normal_decel_evidence','watchdog_decel_evidence','inflight_evidence'):
            self.assertEqual(record[key],getattr(a,key))
        self.assertEqual(record['parameters']['normal_decel'],9000)
    def test_short_write_still_waits_declared_inflight_horizon(self):
        class Short(Bench):
            def write(self,data):
                if data==b'VEL 1250\n':return 2
                return super().write(data)
        f=Short();link=Link(f,f.clock,f.sleep)
        with self.assertRaises(Abort):execute(link,options(margin_mm=1,watchdog_decel=9000,
                                                        inflight_ms=280,window_s=.139))
        attempt=next(e['value'] for e in link.events if e['direction']=='nonzero_attempt')
        horizon=next(e['value'] for e in link.events if e['direction']=='inflight_horizon')
        stopped=next(e['t'] for e in link.events if e['direction']=='stop')
        self.assertAlmostEqual(horizon,attempt+.280)
        self.assertGreaterEqual(stopped,horizon+.2)
    def test_horizon_log_failure_cannot_skip_stop(self):
        f=Bench();link=Link(f,f.clock,f.sleep);record=link.record
        def broken(direction,value):
            if direction=='inflight_horizon':raise Abort('日志内存预算耗尽')
            record(direction,value)
        link.record=broken
        with self.assertRaisesRegex(Abort,'日志'):execute(link,options())
        self.assertEqual(f.v,0)
        self.assertIn('VEL 0',f.writes[f.writes.index('VEL 1250')+1:])
    def test_all_logging_failures_after_nonzero_still_attempt_zero(self):
        f=Bench();link=Link(f,f.clock,f.sleep);record=link.record
        def broken(direction,value):
            if 'VEL 1250' in f.writes:raise Abort('日志预算耗尽')
            record(direction,value)
        link.record=broken
        with self.assertRaises(Abort):execute(link,options())
        self.assertEqual(f.v,0)
        self.assertIn('VEL 0',f.writes[f.writes.index('VEL 1250')+1:])
        self.assertLess(f.t,3)
    def test_secondary_abort_log_failure_does_not_hide_stop_warning(self):
        import contextlib,io
        from unittest.mock import patch,Mock
        import step50k_probe as probe
        f=Bench();link=Link(f,f.clock,f.sleep)
        link.record=Mock(side_effect=Abort('日志内存预算耗尽'))
        with patch.object(probe.Path,'open'),patch('serial.Serial'),patch.object(probe,'Link',return_value=link),patch.object(probe,'execute',side_effect=Abort('停车未确认，请独立断电')),contextlib.redirect_stdout(io.StringIO()) as output:
            result=probe.main(['run','--port','unused','--out','unused'])
        self.assertEqual(result,1)
        self.assertIn('停车未确认',output.getvalue())
        self.assertIn('日志记录失败',output.getvalue())
    def test_clock_failure_after_nonzero_still_attempts_zero_without_clock(self):
        class BrokenClock(Bench):
            clock_failed=False
            def clock(self):
                if self.clock_failed:raise OSError('单调时钟不可用')
                return self.t
            def write(self,data):
                count=super().write(data)
                if data==b'VEL 1250\n':self.clock_failed=True
                return count
        f=BrokenClock();link=Link(f,f.clock,f.sleep)
        with self.assertRaisesRegex(Abort,'停车未确认'):execute(link,options())
        self.assertEqual(f.v,0)
        self.assertIn('VEL 0',f.writes[f.writes.index('VEL 1250')+1:])
        self.assertFalse(any(e['direction']=='result' for e in link.events))
