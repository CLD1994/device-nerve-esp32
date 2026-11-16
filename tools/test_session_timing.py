"""纯计时观测，不连接设备或调度运动。"""
import unittest
from session_timing import SessionTiming

class TimingTest(unittest.TestCase):
    def test_attempts_completions_and_received_state_are_distinct(self):
        now=[10.];t=SessionTiming(lambda:now[0])
        now[0]=11;t.write_attempt(600)
        now[0]=11.02;t.write_complete(600)
        now[0]=11.1;t.state(100)
        now[0]=12;t.write_attempt(600) # 失败写没有complete
        now[0]=13;t.write_attempt(0)
        now[0]=13.01;t.write_complete(0)
        now[0]=13.3;t.mark('stop_observed')
        now[0]=14;t.finish()
        r=t.report()
        self.assertEqual(r['first_nonzero_attempt_s'],1)
        self.assertEqual(r['last_nonzero_attempt_s'],2)
        self.assertAlmostEqual(r['last_nonzero_complete_s'],1.02)
        self.assertAlmostEqual(r['first_nonzero_vx_received_s'],1.1)
        self.assertEqual(r['peak_abs_received_vx_mm_s'],100)
        self.assertEqual(r['command_elapsed_s'],4)
    def test_hold_cannot_invent_zero_or_stop_confirmation(self):
        t=SessionTiming(lambda:0)
        t.write_attempt(600);t.write_complete(600);t.state(0);t.finish()
        r=t.report()
        self.assertIsNone(r['first_zero_attempt_s'])
        self.assertIsNone(r['stop_observed_s'])
        self.assertIsNone(r['first_nonzero_vx_received_s'])
    def test_query_only_has_no_motion_measurements(self):
        t=SessionTiming(lambda:0);t.state(0);t.finish()
        self.assertIsNone(t.report()['first_nonzero_attempt_s'])
    def test_preflight_velocity_is_not_current_response_or_peak(self):
        now=[0.];t=SessionTiming(lambda:now[0]);t.state(900)
        now[0]=1;t.write_attempt(600)
        now[0]=1.1;t.state(50)
        r=t.report()
        self.assertEqual(r['received_state_samples'],1)
        self.assertEqual(r['peak_abs_received_vx_mm_s'],50)
        self.assertAlmostEqual(r['received_response_interval_s'],.1)
    def test_repeated_zero_does_not_replace_first(self):
        now=[0.];t=SessionTiming(lambda:now[0])
        now[0]=1;t.write_attempt(0);t.write_complete(0)
        now[0]=2;t.write_attempt(0);t.write_complete(0)
        self.assertEqual(t.report()['first_zero_attempt_s'],1)

class HumanSummaryTest(unittest.TestCase):
    def test_human_lines_distinguish_timepoints_intervals_and_units(self):
        now=[0.];t=SessionTiming(lambda:now[0])
        now[0]=.5;t.mark('preflight_complete');t.write_attempt(600)
        now[0]=.502;t.write_complete(600)
        now[0]=.52;t.state(600)
        now[0]=1.5;t.write_attempt(0);t.write_complete(0)
        now[0]=1.75;t.mark('stop_observed')
        now[0]=2;t.finish()
        before=t.report();text=t.summary()
        self.assertNotIn('{',text)
        self.assertIn('入口后',text)
        self.assertIn('0.500 s',text)
        self.assertIn('20.0 ms',text)
        self.assertIn('250.0 ms',text)
        self.assertIn('600 mm/s',text)
        self.assertIn('2.000 s',text)
        self.assertIn('不代表',text)
        self.assertEqual(t.report(),before)
    def test_missing_events_are_not_zero_or_json_null(self):
        t=SessionTiming(lambda:0);t.finish();text=t.summary()
        self.assertIn('未发生',text)
        self.assertIn('未确认',text)
        self.assertIn('未观测',text)
        self.assertNotIn('null',text)

class TargetAccelerationTimingTest(unittest.TestCase):
    def test_uses_requested_1000_and_95_percent_not_velmax(self):
        now=[0.];t=SessionTiming(lambda:now[0])
        t.state(1250)
        now[0]=1;t.write_attempt(1000);t.write_complete(1000)
        now[0]=1.1;t.state(949)
        self.assertIsNone(t.report()['target_95_received_s'])
        now[0]=1.2;t.state(950)
        now[0]=1.3;t.state(996)
        r=t.report()
        self.assertEqual(r['target_velocity_mm_s'],1000)
        self.assertEqual(r['target_95_threshold_mm_s'],950)
        self.assertAlmostEqual(r['target_95_interval_s'],.2)
        self.assertIn('95%',t.summary())
        self.assertIn('1000',t.summary())
        self.assertIn('95%',t.summary().splitlines()[1])
        self.assertEqual(len(t.summary().splitlines()),8)
    def test_negative_target_needs_negative_received_velocity(self):
        now=[0.];t=SessionTiming(lambda:now[0]);t.write_attempt(-1000);t.write_complete(-1000)
        t.state(1000);t.state(-949)
        self.assertIsNone(t.report()['target_95_received_s'])
        now[0]=.2;t.state(-950)
        self.assertAlmostEqual(t.report()['target_95_interval_s'],.2)
    def test_short_write_and_after_zero_cannot_claim_target(self):
        t=SessionTiming(lambda:0);t.write_attempt(1000);t.state(996)
        self.assertIsNone(t.report()['target_95_received_s'])
        self.assertIn('未确认完整非零写入',t.summary())
        t.write_complete(1000);t.write_attempt(0);t.state(996)
        self.assertIsNone(t.report()['target_95_received_s'])
        self.assertIn('未观测到达成',t.summary())
    def test_no_motion_no_estimate(self):
        t=SessionTiming(lambda:0);t.state(1000);t.write_attempt(0);t.write_complete(0)
        self.assertIsNone(t.report()['target_95_interval_s'])
        self.assertIsNone(t.report()['target_velocity_mm_s'])

    def test_zero_before_nonzero_excludes_target_estimate(self):
        t=SessionTiming(lambda:0);t.write_attempt(0);t.write_complete(0)
        t.write_attempt(1000);t.write_complete(1000);t.state(996)
        self.assertIsNone(t.report()['target_95_received_s'])

class AccelerationPeakTest(unittest.TestCase):
    def test_peak_time_first_occurrence_and_zero_exclusion(self):
        now=[0.];t=SessionTiming(lambda:now[0]);t.write_attempt(1000);t.write_complete(1000)
        now[0]=.1;t.state(800)
        now[0]=.2;t.state(700)
        now[0]=.3;t.state(800)
        t.write_attempt(0)
        now[0]=.4;t.state(900)
        r=t.report()
        self.assertEqual(r['acceleration_peak_velocity_mm_s'],800)
        self.assertAlmostEqual(r['acceleration_peak_interval_s'],.1)
        self.assertIn('800',t.summary())
    def test_negative_peak_and_unknown_latest_are_separate(self):
        now=[0.];t=SessionTiming(lambda:now[0]);t.write_attempt(-1000);t.write_complete(-1000)
        t.state(900);now[0]=.2;t.state(-800)
        t.finish(latest_velocity=0)
        r=t.report()
        self.assertEqual(r['acceleration_peak_velocity_mm_s'],-800)
        self.assertEqual(r['latest_valid_velocity_mm_s'],0)
        self.assertAlmostEqual(r['acceleration_peak_interval_s'],.2)
    def test_no_valid_acceleration_samples(self):
        t=SessionTiming(lambda:0);t.write_attempt(1000);t.state(900);t.finish()
        self.assertIsNone(t.report()['acceleration_peak_velocity_mm_s'])
        self.assertIsNone(t.report()['latest_valid_velocity_mm_s'])
