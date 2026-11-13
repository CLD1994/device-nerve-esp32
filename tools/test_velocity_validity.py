"""通过串口字节入口检查测量有效性与运动门禁。"""
import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

import cartpole_host as host
import max_accel_run as accel
from host_test_support import session, receive
from velocity_validity import VelocityValidity


class ValidityTest(unittest.TestCase):
    def test_unknown_blocks_nonzero(self):
        rig, port, _, _ = session(host.Rig)
        receive(rig, port, 'STATE 1 2 0 0')
        with self.assertRaises(RuntimeError):
            rig.send_line('VEL 20')
        self.assertEqual(port.writes, [])

    def test_invalid_clears_state_and_recovery_does_not_resume(self):
        rig, port, _, _ = session(host.Rig)
        receive(rig, port, 'VEL_VALID 1 1', 'STATE 1 2 0 0')
        rig.send_line('VEL 20')
        with self.assertRaises(RuntimeError):
            receive(rig, port, 'VEL_VALID 0 1')
        self.assertIsNone(rig.last_state)
        with self.assertRaises(RuntimeError):
            receive(rig, port, 'VEL_VALID 1 1')
        with self.assertRaises(RuntimeError):
            receive(rig, port, 'STATE 1 2 0 0')
        with self.assertRaises(RuntimeError):
            rig.send_line('VEL 20')
        rig.send_line('VEL 0')
        self.assertEqual(port.writes, [b'VEL 20\n', b'VEL 0\n'])

    def test_malformed_validity_invalidates(self):
        rig, port, _, _ = session(host.Rig)
        receive(rig, port, 'VEL_VALID 1 1', 'STATE 1 2 0 0', 'VEL_VALID 2 1')
        self.assertIsNone(rig.last_state)
        with self.assertRaises(RuntimeError):
            rig.send_line('VEL 20')

    def test_partial_lines_survive_pump_boundary(self):
        rig, port, _, _ = session(host.Rig)
        port.feed(b'VEL_VAL')
        rig.pump(.005)
        self.assertIsNone(rig.last_state)
        port.feed(b'ID 1 1\nSTATE 1 2', b' 0 0\n')
        rig.pump(.005)
        rig.send_line('VEL 20')
        self.assertEqual(rig.last_state, ['1', '2', '0', '0'])
        self.assertEqual(rig.unknown_count, 0)


class ValidityHeartbeatTest(unittest.TestCase):
    def test_stale_heartbeat_latches_even_after_recovery(self):
        now = [0.]
        validity = VelocityValidity(lambda: now[0])
        validity.update(['VEL_VALID', '1', '1'])
        validity.command('VEL 20')
        now[0] = .301
        with self.assertRaises(RuntimeError):
            validity.require()
        validity.update(['VEL_VALID', '1', '1'])
        with self.assertRaises(RuntimeError):
            validity.require()

    def test_initial_invalid_can_recover_before_motion(self):
        validity = VelocityValidity(lambda: 0.)
        validity.update(['VEL_VALID', '0', '1'])
        self.assertFalse(validity.ready())
        validity.update(['VEL_VALID', '1', '1'])
        self.assertTrue(validity.ready())

    def test_invalid_during_max_accel_clears_samples(self):
        rig, port, _, _ = session(accel.TestRig)
        receive(rig, port, 'VEL_VALID 1 1', 'STATE 1 2 0 0')
        self.assertEqual(rig.last_state_tuple(), (1, 0))
        rig.send_line('VEL 20')
        with self.assertRaises(accel.ExperimentAborted):
            receive(rig, port, 'VEL_VALID 1 0')
        self.assertIsNone(rig.last_state_tuple())
        with self.assertRaises(accel.ExperimentAborted):
            receive(rig, port, 'VEL_VALID 1 1')
        with self.assertRaises(accel.ExperimentAborted):
            receive(rig, port, 'STATE 1 2 0 0')
        self.assertIsNone(rig.last_state_tuple())

    def test_malformed_then_state_must_not_repopulate(self):
        rig, port, _, _ = session(host.Rig)
        receive(rig, port, 'VEL_VALID 1 1', 'STATE 1 2 0 0', 'VEL_VALID 1', 'STATE 1 2 0 0')
        self.assertIsNone(rig.last_state)

    def test_late_heartbeat_cannot_hide_gap(self):
        now = [0.]
        validity = VelocityValidity(lambda: now[0])
        validity.update(['VEL_VALID', '1', '1'])
        validity.command('VEL 20')
        now[0] = .4
        validity.update(['VEL_VALID', '1', '1'])
        self.assertFalse(validity.ready())


class HostFailureTest(unittest.TestCase):
    def test_active_unknown_latches_and_clears_both_caches(self):
        for line in ('VEL_VALI 0 1', 'STATE 1 bad 0 0', 'MODE READY', 'OK VALUE bad'):
            with self.subTest(line=line):
                rig, port, _, messages = session(accel.TestRig)
                receive(rig, port, 'VEL_VALID 1 1', 'STATE 1 2 0 0')
                rig.send_line('VEL 20')
                with self.assertRaises(accel.ExperimentAborted):
                    receive(rig, port, line)
                self.assertEqual(messages, [])
                self.assertIsNone(rig.last_state)
                self.assertIsNone(rig.last_state_tuple())
                with self.assertRaises(RuntimeError):
                    rig.send_line('VEL 20')
                rig.send_line('VEL 0')
                rig.send_line('DISABLE')
                self.assertEqual(port.writes[-2:], [b'VEL 0\n', b'DISABLE\n'])

    def test_serial_writes_are_bounded_without_flush(self):
        rig, port, _, _ = session(host.Rig)
        self.assertEqual(port.open_options, ('memory', 460800, .2, .02))
        rig.send_line('VEL 0')
        self.assertEqual(port.writes, [b'VEL 0\n'])
        self.assertEqual(port.flush_count, 0)

    def test_partial_serial_write_fails(self):
        rig, port, _, _ = session(host.Rig)
        port.write_limit = 2
        with self.assertRaises(RuntimeError):
            rig.send_line('VEL 0')

    def test_handler_stops_before_output(self):
        events = []
        rig = Mock(spec=host.Rig)
        rig.velocity_validity = SimpleNamespace(active=True)
        rig.send_line.side_effect = lambda cmd: events.append(cmd)
        with patch.object(host, 'Rig', return_value=rig), \
                patch.object(host, 'cmd_query', side_effect=RuntimeError('invalid')), \
                patch.object(host.sys, 'argv', ['tool', '--port', 'unused', 'query']), \
                patch('builtins.print', side_effect=lambda *args: events.append('print')):
            with self.assertRaises(SystemExit) as result:
                host.main()
        self.assertEqual(result.exception.code, 1)
        self.assertEqual(events[0], 'VEL 0')

    def test_state_does_not_display_stale_cached_position(self):
        rig, port, clock, _ = session(host.Rig)
        receive(rig, port, 'STATE 123 2 0 0')
        clock.advance(.2)
        with patch.object(host.time, 'time', side_effect=[0., 0., 1., 1.]), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(host.cmd_state(rig, SimpleNamespace(secs=1.)), 1)
        self.assertNotIn('x_um', out.getvalue())

    def test_pump_aborts_before_printing_later_lines(self):
        rig, port, _, messages = session(host.Rig)
        receive(rig, port, 'VEL_VALID 1 1', 'STATE 1 2 0 0')
        rig.send_line('VEL 20')
        port.feed(b'VEL_VALI 0 1\nMODE READY NONE\n')
        with self.assertRaises(RuntimeError):
            rig.pump(.1)
        self.assertEqual(messages, [])
        self.assertIsNone(rig.last_mode)

    def test_test_rig_pump_surfaces_experiment_abort(self):
        rig, port, _, _ = session(accel.TestRig)
        receive(rig, port, 'VEL_VALID 1 1', 'STATE 1 2 0 0')
        rig.send_line('VEL 20')
        with self.assertRaises(accel.ExperimentAborted):
            receive(rig, port, 'VEL_VALI 0 1')

    def test_injected_log_lifetime_and_sample_time(self):
        log = io.StringIO()
        rig, port, clock, _ = session(accel.TestRig, log_sink=log)
        receive(rig, port, 'VEL_VALID 1 1', 'STATE 1 2 0 0')
        self.assertEqual(rig.last_state_tuple(), (1, 0))
        self.assertIn('STATE 1 2 0 0', log.getvalue())
        rig.close()
        self.assertTrue(port.closed)
        self.assertFalse(log.closed)
