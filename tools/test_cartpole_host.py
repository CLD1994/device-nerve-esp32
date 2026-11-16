"""串口联调工具单元测试；串口与时间均使用替身，不连接设备。"""
import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cartpole_host as host
from host_test_support import session, receive


class RigStateTest(unittest.TestCase):
    def make_rig(self):
        rig, self.port, _, _ = session(host.Rig)
        return rig

    def test_no_initial_state(self):
        rig = self.make_rig()
        self.assertIsNone(rig.last_state)

    def test_invalid_state_does_not_create_sample(self):
        rig = self.make_rig()
        with contextlib.redirect_stdout(io.StringIO()):
            receive(rig, self.port, "STATE invalid 0 0 0")
        self.assertIsNone(rig.last_state)
        self.assertEqual(rig.state_count, 0)
        self.assertEqual(rig.unknown_count, 1)

    def test_valid_state_sets_latest_sample(self):
        rig = self.make_rig()
        receive(rig, self.port, "STATE 80 -3141593 0 0")
        self.assertEqual(rig.last_state, ["80", "-3141593", "0", "0"])
        self.assertEqual(rig.state_count, 1)

    def test_state_without_frames_returns_failure(self):
        rig = self.make_rig()
        with patch.object(rig, "pump"), \
                patch.object(host.time, "time", side_effect=[0.0, 0.0, 1.0, 1.0]), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result = host.cmd_state(rig, SimpleNamespace(secs=1.0))
        self.assertEqual(result, 1)
        self.assertEqual(rig.state_count, 0)
        self.assertNotIn("x_um", output.getvalue())
        self.assertEqual(self.port.writes, [])


class StateRateTest(unittest.TestCase):
    def run_state(self, count, expected, unknown=0):
        rig = SimpleNamespace(last_state=None, state_count=0, unknown_count=0)
        def pump(duration):
            rig.state_count = count
            rig.unknown_count = unknown
        rig.pump = pump
        with patch.object(host.time, "time", side_effect=[0.0, 0.0, 1.0, 1.0]), \
                contextlib.redirect_stdout(io.StringIO()):
            return host.cmd_state(rig, SimpleNamespace(secs=1.0, expected_hz=expected))

    def test_explicit_rate_accepts_500_hz(self):
        self.assertEqual(self.run_state(500, 500), 0)

    def test_explicit_rate_rejects_old_firmware_rate(self):
        self.assertEqual(self.run_state(200, 500), 1)

    def test_legacy_rate_can_be_checked_explicitly(self):
        self.assertEqual(self.run_state(200, 200), 0)

    def test_no_expected_rate_only_checks_data_quality(self):
        self.assertEqual(self.run_state(500, None), 0)
        self.assertEqual(self.run_state(0, None), 1)
        self.assertEqual(self.run_state(500, None, unknown=1), 1)

    def test_invalid_cli_measurement_options_do_not_open_port(self):
        for option, value in [("--secs", "0"), ("--secs", "nan"),
                              ("--expected-hz", "0"), ("--expected-hz", "inf")]:
            with self.subTest(option=option, value=value), \
                    patch.object(host.sys, "argv", ["tool", "--port", "unused", "state", option, value]), \
                    patch.object(host, "Rig") as rig, \
                    contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as result:
                host.main()
            self.assertEqual(result.exception.code, 2)
            rig.assert_not_called()

    def test_rate_tolerance_is_one_hz(self):
        self.assertEqual(self.run_state(499, 500), 0)
        self.assertEqual(self.run_state(501, 500), 0)
        self.assertEqual(self.run_state(498, 500), 1)


class CalibrationCommandTest(unittest.TestCase):
    def rig(self, response):
        rig = SimpleNamespace(last_reply=("OK", "CONFIRM_LEFT", -1), replies={})
        rig.sent = []
        rig.send_line = rig.sent.append
        rig.pump = lambda duration: setattr(rig, "last_reply", response)
        return rig

    def test_confirm_requires_matching_ack(self):
        for response, expected in [(None, 1), (("OK", "OTHER", 0), 1),
                                   (("ERR", "CONFIRM_LEFT", None), 1),
                                   (("OK", "CONFIRM_LEFT", -250000), 0)]:
            with self.subTest(response=response):
                rig = self.rig(response)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(host.cmd_confirm_left(rig, None), expected)
                self.assertEqual(rig.sent, ["CONFIRM LEFT"])

    def test_status_requires_terminal_response(self):
        rig = self.rig(("OK", "CAL_STORAGE", 0))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(host.cmd_calib_status(rig, None), 1)
        rig.pump = lambda duration: rig.replies.update(
            CAL_STATE=3, CAL_LENGTH_UM=500000, CAL_SAVED=1, CAL_STORAGE=0)
        self.assertEqual(host.cmd_calib_status(rig, None), 0)
        self.assertEqual(rig.sent, ["CALIB?", "CALIB?"])
        rig.pump = lambda duration: None
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(host.cmd_calib_status(rig, None), 1)

class DisableCommandTest(unittest.TestCase):
    def test_success_requires_fresh_disabled_response(self):
        from unittest.mock import Mock
        rig=Mock(last_mode=('DISABLED','NONE'), last_reply=None)
        def pump(_): rig.last_mode=('DISABLED','NONE')
        rig.pump.side_effect=pump
        self.assertEqual(host.cmd_disable(rig, SimpleNamespace()),0)
        rig.send_line.assert_called_once_with('DISABLE')

    def test_stale_mode_timeout_busy_and_fault_are_not_success(self):
        from unittest.mock import Mock
        for response in (None, ('ERR','BUSY',None), ('FAULT','POWER')):
            rig=Mock(last_mode=('DISABLED','NONE'),last_reply=None)
            def pump(_,r=response):
                if r and r[0]=='ERR': rig.last_reply=r
                elif r: rig.last_mode=r
            rig.pump.side_effect=pump
            self.assertEqual(host.cmd_disable(rig,SimpleNamespace()),1)
            rig.send_line.assert_called_once_with('DISABLE')


class StepLossEventTest(unittest.TestCase):
    def active(self, **kwargs):
        rig, port, clock, messages = session(host.Rig, **kwargs)
        receive(rig, port, 'VEL_VALID 1 1', 'STATE 10 20 0 0')
        rig.send_line('VEL 20')
        return rig, port, clock, messages

    def test_default_report_keeps_active_state_and_sends_nothing(self):
        rig, port, _, messages = self.active()
        receive(rig, port, 'EVENT STEP_LOSS 2 2 123456789')
        self.assertEqual(rig.unknown_count, 0)
        self.assertEqual(rig.state_count, 1)
        self.assertEqual(rig.last_state, ['10', '20', '0', '0'])
        self.assertFalse(rig.velocity_validity.failed)
        self.assertEqual(rig.event_count, 1)
        self.assertEqual(rig.last_step_loss_event['device_us'], 123456789)
        self.assertEqual(rig.last_step_loss_event['event_id'], 2)
        self.assertEqual(rig.last_step_loss_event['run_id'], 2)
        self.assertIsNone(rig.last_mode)
        self.assertTrue(any('EVENT STEP_LOSS 2 2 123456789' in m for m in messages))
        self.assertEqual(port.writes, [b'VEL 20\n'])
        rig.send_line('VEL 20')
        self.assertEqual(port.writes[-1], b'VEL 20\n')

    def test_duplicate_event_is_counted_without_inventing_new_run(self):
        rig, port, _, _ = self.active()
        receive(rig, port, 'EVENT STEP_LOSS 2 2 123', 'EVENT STEP_LOSS 2 2 123')
        self.assertEqual(rig.event_count, 2)
        self.assertEqual(rig.last_step_loss_event['run_id'], 2)

    def test_inactive_stop_reports_without_motion(self):
        rig, port, _, messages = session(host.Rig, step_loss_policy='stop')
        receive(rig, port, 'EVENT STEP_LOSS 1 1 0')
        self.assertEqual(rig.event_count, 1)
        self.assertFalse(rig.velocity_validity.failed)
        self.assertTrue(messages)
        self.assertEqual(port.writes, [])

    def test_uint_boundaries_are_valid(self):
        rig, port, _, _ = self.active()
        receive(rig, port, 'EVENT STEP_LOSS 4294967295 4294967295 9223372036854775807')
        self.assertEqual(rig.event_count, 1)
        self.assertEqual(rig.unknown_count, 0)

    def test_malformed_and_unknown_events_keep_existing_failure(self):
        bad = ['EVENT STEP_LOSS 0 1 0','EVENT STEP_LOSS 1 0 0',
               'EVENT STEP_LOSS -1 1 0','EVENT STEP_LOSS 1 1 -1',
               'EVENT STEP_LOSS 4294967296 1 0','EVENT STEP_LOSS 1 4294967296 0',
               'EVENT STEP_LOSS 1 1 9223372036854775808',
               'EVENT STEP_LOSS +1 1 0','EVENT STEP_LOSS 1_0 1 0',
               'EVENT STEP_LOSS one 1 0','EVENT OTHER 1 1 0',
               'EVENT STEP_LOSS 1 1','EVENT STEP_LOSS 1 1 0 extra',
               'EVENT STEP_LOSS '+'0'*10000+'1 1 0']
        for line in bad:
            with self.subTest(line=line[:80]):
                rig, port, _, messages = self.active()
                port.feed((line+"\n").encode("ascii"))
                with self.assertRaises(RuntimeError):rig.pump(.1)
                self.assertEqual(rig.unknown_count,1)
                self.assertEqual(rig.event_count,0)
                self.assertIsNone(rig.last_state)
                self.assertTrue(rig.velocity_validity.failed)
                self.assertEqual(messages,[])

    def test_report_does_not_disable_other_gates(self):
        for fault in ['VEL_VALID 0 1','BAD LINE']:
            rig, port, _, _ = self.active()
            receive(rig,port,'EVENT STEP_LOSS 1 1 0')
            with self.assertRaises(RuntimeError):receive(rig,port,fault)
            with self.assertRaises(RuntimeError):rig.send_line('VEL 20')
        rig, port, _, _ = self.active()
        receive(rig,port,'EVENT STEP_LOSS 1 1 0','MODE FAULT POWER')
        self.assertEqual(rig.last_mode,('FAULT','POWER'))

    def test_stop_records_then_latches_without_stdout_before_zero_request(self):
        rig, port, _, messages = self.active(step_loss_policy='stop')
        with self.assertRaisesRegex(RuntimeError,'STEP_LOSS.*2.*2.*123'):
            receive(rig,port,'EVENT STEP_LOSS 2 2 123')
        self.assertEqual(rig.event_count,1)
        self.assertEqual(rig.last_step_loss_event['event_id'],2)
        self.assertEqual(messages,[])
        self.assertTrue(rig.velocity_validity.failed)
        with self.assertRaises(RuntimeError):rig.send_line('VEL 20')
        rig.send_line('VEL 0')
        self.assertEqual(port.writes,[b'VEL 20\n',b'VEL 0\n'])

    def test_invalid_policy_never_opens_port(self):
        from unittest.mock import Mock
        factory=Mock()
        with self.assertRaises(ValueError):host.Rig('unused',serial_factory=factory,step_loss_policy='other')
        factory.assert_not_called()

    def test_main_stop_sends_zero_before_print_and_no_more_motion(self):
        rig, port, _, _ = self.active(step_loss_policy='stop')
        def command(rig,args):
            receive(rig,port,'EVENT STEP_LOSS 2 2 123')
            rig.send_line('VEL 20')
        def printed(*args,**kwargs):
            self.assertEqual(port.writes[-1],b'VEL 0\n')
        with patch.object(host.sys,'argv',['tool','--port','memory','--step-loss-policy','stop','vel','20']), \
                patch.object(host,'Rig',return_value=rig) as factory, \
                patch.object(host,'cmd_vel',side_effect=command),patch('builtins.print',side_effect=printed), \
                self.assertRaises(SystemExit) as result:
            host.main()
        self.assertEqual(result.exception.code,1)
        self.assertEqual(port.writes,[b'VEL 20\n',b'VEL 0\n'])
        self.assertTrue(port.closed)
        self.assertEqual(factory.call_args.kwargs['step_loss_policy'],'stop')

    def test_report_preserves_reply_mode_and_state_timestamp(self):
        rig, port, _, _ = self.active()
        receive(rig,port,'MODE READY NONE','OK VEL_MAX 1250')
        old=(rig.last_reply,dict(rig.replies),rig.last_mode,rig.state_received_at)
        receive(rig,port,'EVENT STEP_LOSS 2 99 123')
        self.assertEqual((rig.last_reply,rig.replies,rig.last_mode,rig.state_received_at),old)
        self.assertEqual(rig.last_step_loss_event['run_id'],99)

    def test_real_cli_query_uses_report_default_and_serial_bytes(self):
        rig_type=host.Rig
        made=[]
        def factory(port,baud,**kwargs):
            rig, transport, _, messages=session(rig_type,**kwargs)
            transport.feed(b'EVENT STEP_LOSS 2 2 123\nMODE DISABLED NONE\n')
            made.append((rig,transport,messages))
            return rig
        with patch.object(host.sys,'argv',['tool','--port','memory','query']), \
                patch.object(host,'Rig',side_effect=factory),self.assertRaises(SystemExit) as result:
            host.main()
        self.assertEqual(result.exception.code,0)
        rig,transport,messages=made[0]
        self.assertEqual(rig.step_loss_policy,'report')
        self.assertEqual(rig.event_count,1)
        self.assertEqual(transport.writes,[b'QUERY\n'])
        self.assertTrue(transport.closed)
        self.assertTrue(any('STEP_LOSS 2 2 123' in m for m in messages))

    def test_invalid_cli_policy_never_opens_port(self):
        with patch.object(host.sys,'argv',['tool','--port','unused','--step-loss-policy','other','query']), \
                patch.object(host,'Rig') as factory,contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):host.main()
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()

class TravelReceiveTest(unittest.TestCase):
    def test_split_frames_and_each_state_callback(self):
        rig,port,_,_=session(host.Rig)
        seen=[]
        rig.state_observer=lambda:seen.append(int(rig.last_state[0]))
        rig._consume(b'STATE 1 0 0')
        rig._consume(b' 0\nSTATE 2 0 0 0\n')
        self.assertEqual(seen,[1,2])
    def test_poll_restores_timeout_after_error(self):
        rig,port,_,_=session(host.Rig)
        port.timeout=.2
        port.in_waiting=0
        rig.poll_available()
        self.assertEqual(port.timeout,.2)
        with patch.object(rig,'_consume',side_effect=RuntimeError('bad')):
            with self.assertRaises(RuntimeError): rig.poll_available()
        self.assertEqual(port.timeout,.2)
    def test_cli_rejects_conflicting_modes_before_port(self):
        for argv in (['--to-limit'],['--max-seconds','nan'],['--hold','1','--plan']):
            with patch.object(host.sys,'argv',['tool','--port','X','vel','600']+argv), patch.object(host,'Rig') as factory, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): host.main()
                factory.assert_not_called()

class TravelMessageObserverTest(unittest.TestCase):
    def test_observer_sees_each_line_before_overwrite(self):
        rig,port,_,_=session(host.Rig)
        seen=[];rig.message_observer=seen.append
        rig._consume(b'MODE FAULT STEP_LOSS\nMODE READY NONE\nERR BUSY\nOK VEL 0\n')
        self.assertEqual(seen,['MODE FAULT STEP_LOSS','MODE READY NONE','ERR BUSY','OK VEL 0'])
        self.assertEqual(rig.last_mode,('READY','NONE'))
        self.assertEqual(rig.last_reply,('OK','VEL',0))


class DefaultTravelCliTest(unittest.TestCase):
    def invoke(self, options):
        with patch.object(host.sys,'argv',['tool','--port','X','vel','600']+options), patch.object(host,'Rig') as factory, patch.object(host,'cmd_vel',return_value=0) as command:
            with self.assertRaises(SystemExit) as exited: host.main()
            self.assertEqual(exited.exception.code,0)
            return command.call_args.args[1]
    def test_default_is_travel_not_one_second(self):
        args=self.invoke([])
        self.assertIsNone(args.hold)
        self.assertEqual(args.inflight_ms,10)
        rig=SimpleNamespace()
        with patch('travel_limit.run',return_value=0) as run:
            self.assertEqual(host.cmd_vel(rig,args),0)
            run.assert_called_once_with(rig,args)
    def test_plan_works_without_selector(self):
        args=self.invoke(['--plan'])
        self.assertTrue(args.plan)
        self.assertIsNone(args.hold)
    def test_explicit_hold_keeps_duration(self):
        args=self.invoke(['--hold','2'])
        self.assertEqual(args.hold,2)
        self.assertFalse(args.plan)

class StartToleranceCliTest(unittest.TestCase):
    def test_invalid_tolerance_rejected_before_port(self):
        for value in ('-1','1.1','nan','inf'):
            with patch.object(host.sys,'argv',['tool','--port','X','vel','600','--start-tolerance-mm',value]),patch.object(host,'Rig') as factory,contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):host.main()
                factory.assert_not_called()
    def test_value_error_is_friendly_without_motion(self):
        rig=SimpleNamespace(velocity_validity=SimpleNamespace(active=False),close=lambda:None)
        with patch.object(host.sys,'argv',['tool','--port','X','vel','600']),patch.object(host,'Rig',return_value=rig),patch('travel_limit.run',side_effect=ValueError('起点超限')),contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as exited:host.main()
            self.assertEqual(exited.exception.code,1)
        self.assertIn('起点超限',output.getvalue())
    def test_active_value_error_requests_zero_before_message(self):
        actions=[]
        rig=SimpleNamespace(velocity_validity=SimpleNamespace(active=True),close=lambda:actions.append('close'),send_line=actions.append)
        with patch.object(host.sys,'argv',['tool','--port','X','vel','600']),patch.object(host,'Rig',return_value=rig),patch('travel_limit.run',side_effect=ValueError('bad')),patch('builtins.print',side_effect=lambda *a:actions.append('print')):
            with self.assertRaises(SystemExit):host.main()
        self.assertEqual(actions[:2],['VEL 0','print'])

class TravelBacklogTest(unittest.TestCase):
    def test_known_backlog_rejected_not_retimestamped_as_fresh(self):
        rig,port,_,_=session(host.Rig)
        port.timeout=.2;port.in_waiting=4097
        with patch.object(port,'read') as read:
            with self.assertRaises(RuntimeError):rig.poll_available()
            read.assert_not_called()
        self.assertTrue(rig.velocity_validity.failed)
        self.assertEqual(rig.max_rx_waiting,4097)
        self.assertEqual(port.timeout,.2)

class TimingHooksTest(unittest.TestCase):
    def test_short_write_records_attempt_not_success(self):
        rig,port,_,_=session(host.Rig)
        rig.timing=host.SessionTiming(rig._clock)
        receive(rig,port,'VEL_VALID 1 1');receive(rig,port,'STATE 0 0 0 0')
        with patch.object(port,'write',return_value=2):
            with self.assertRaises(RuntimeError):rig.send_line('VEL 600')
        self.assertEqual(rig.timing.report()['nonzero_write_attempts'],1)
        self.assertIsNone(rig.timing.report()['first_nonzero_complete_s'])
    def test_hold_keeps_existing_pumps_without_zero(self):
        writes=[];pumps=[]
        rig=SimpleNamespace(query=lambda:('READY','NONE'),send_line=writes.append,pump=pumps.append,last_state=None)
        with patch.object(host.time,'time',side_effect=[0,0,.5,1]),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(host.cmd_vel(rig,SimpleNamespace(hold=1,v=600)),0)
        self.assertEqual(writes,['VEL 600','VEL 600'])
        self.assertEqual(pumps,[.005,.005,.3])
        self.assertIsNone(rig.timing.report()['stop_observed_s'])
    def test_summary_failure_does_not_change_result_or_skip_close(self):
        actions=[];rig=SimpleNamespace(close=lambda:actions.append('close'))
        def cmd(r,a):
            r.timing=host.SessionTiming(lambda:0)
            return 0
        with patch.object(host.sys,'argv',['tool','--port','X','vel','600']),patch.object(host,'Rig',return_value=rig),patch.object(host,'cmd_vel',side_effect=cmd),patch.object(host.SessionTiming,'summary',side_effect=ValueError('summary')):
            with self.assertRaises(SystemExit) as end:host.main()
        self.assertEqual(end.exception.code,0)
        self.assertEqual(actions,['close'])
    def test_no_timing_does_not_parse_or_change_console_payload(self):
        rig,port,_,_=session(host.Rig)
        receive(rig,port,'VEL_VALID 1 1');receive(rig,port,'STATE 0 0 0 0')
        rig.send_line('VEL invalid')
        self.assertEqual(port.writes[-1],b'VEL invalid\n')
        self.assertIsNone(rig.timing)

class StopObservationTest(unittest.TestCase):
    def test_failed_motion_can_observe_new_valid_state_not_resume(self):
        rig,port,_,_=session(host.Rig)
        rig.velocity_validity.active=True;rig.velocity_validity.failed=True
        rig.begin_stop_observation()
        rig._consume(b'VEL_VALID 1 1\nSTATE 10 0 0 0\n')
        self.assertEqual(rig.last_state,['10','0','0','0'])
        self.assertTrue(rig.velocity_validity.failed)
        with self.assertRaises(RuntimeError):rig.send_line('VEL 1')
        rig.send_line('VEL 0')
    def test_bad_frame_requires_new_heartbeat_and_state(self):
        rig,port,_,_=session(host.Rig)
        rig.velocity_validity.active=True;rig.velocity_validity.failed=True
        rig.begin_stop_observation()
        rig._consume(b'VEL_VALID 1 1\nSTATE 10 0 0 0\n')
        for bad in (b'UNKNOWN\n',b'VEL_VALID 0 1\n',b'STATE invalid\n'):
            with self.assertRaises(RuntimeError):rig._consume(bad)
            self.assertIsNone(rig.last_state)
            rig._consume(b'STATE 10 0 0 0\n')
            self.assertIsNone(rig.last_state)
            rig._consume(b'VEL_VALID 1 1\nSTATE 10 0 0 0\n')
            self.assertEqual(rig.last_state,['10','0','0','0'])
    def test_failed_gate_can_collect_full_stillness_window(self):
        from travel_limit import Stillness
        rig,port,clock,_=session(host.Rig)
        rig.velocity_validity.active=True;rig.velocity_validity.failed=True
        rig.begin_stop_observation()
        stable=Stillness(rig);rig.state_observer=stable.observe
        for _ in range(6):
            rig._consume(b'VEL_VALID 1 1\nSTATE 10 0 0 0\n')
            clock.advance(.05)
        self.assertTrue(stable.confirmed)
        self.assertTrue(rig.velocity_validity.failed)
        with self.assertRaises(RuntimeError):rig.send_line('ENABLE')
        with self.assertRaises(RuntimeError):rig.send_line('VEL 100')
    def test_stop_entry_requires_new_heartbeat_not_previous_one(self):
        rig,port,_,_=session(host.Rig)
        receive(rig,port,'VEL_VALID 1 1');receive(rig,port,'STATE 10 0 0 0')
        rig.begin_stop_observation()
        self.assertIsNone(rig.last_state)
        rig._consume(b'STATE 10 0 0 0\n')
        self.assertIsNone(rig.last_state)
    def test_backlog_and_buffer_errors_invalidate_stop_qualification(self):
        for source in ('backlog','buffer'):
            rig,port,_,_=session(host.Rig)
            rig.begin_stop_observation()
            rig._consume(b'VEL_VALID 1 1\nSTATE 10 0 0 0\n')
            with self.subTest(source=source),self.assertRaises(RuntimeError):
                if source=='backlog':
                    port.timeout=.2;port.in_waiting=4097;rig.poll_available()
                else:rig._consume(b'x'*65537)
            self.assertIsNone(rig.last_state)
            self.assertIsNone(rig.stop_observation.received_at)


class StopAwaitHeartbeatTest(unittest.TestCase):
    def test_initial_states_wait_without_fault_until_new_heartbeat(self):
        from travel_limit import Stillness
        rig,port,clock,_=session(host.Rig)
        rig.velocity_validity.active=True
        rig.begin_stop_observation()
        stationary=Stillness(rig);rig.state_observer=stationary.observe
        rig._consume(b'STATE 10 0 0 0\nSTATE 10 0 0 0\n')
        self.assertIsNone(rig.last_state)
        self.assertFalse(rig.velocity_validity.failed)
        self.assertFalse(stationary.confirmed)
        for _ in range(6):
            rig._consume(b'VEL_VALID 1 1\nSTATE 10 0 0 0\n');clock.advance(.05)
        self.assertTrue(stationary.confirmed)
        # 原运动有效性在这个构造中未知，会按原规则锁存；观测不修改它。
    def test_expired_established_observation_is_failure(self):
        rig,port,clock,_=session(host.Rig)
        rig.begin_stop_observation();rig._consume(b'VEL_VALID 1 1\n')
        clock.advance(.301)
        with self.assertRaises(RuntimeError):rig._consume(b'STATE 10 0 0 0\n')

class LatestTimingVelocityTest(unittest.TestCase):
    def test_fresh_valid_last_received_value_even_if_failed_latched(self):
        rig,port,_,_=session(host.Rig)
        receive(rig,port,'VEL_VALID 1 1');receive(rig,port,'STATE 0 0 -800 0')
        rig.velocity_validity.failed=True
        self.assertEqual(host.latest_velocity_for_timing(rig),-800)
        self.assertTrue(rig.velocity_validity.failed)
    def test_missing_invalid_and_old_telemetry_are_unconfirmed(self):
        rig,port,clock,_=session(host.Rig)
        self.assertIsNone(host.latest_velocity_for_timing(rig))
        receive(rig,port,'VEL_VALID 1 1');receive(rig,port,'STATE 0 0 0 0')
        clock.advance(.101)
        self.assertIsNone(host.latest_velocity_for_timing(rig))
        receive(rig,port,'VEL_VALID 0 1')
        self.assertIsNone(host.latest_velocity_for_timing(rig))
