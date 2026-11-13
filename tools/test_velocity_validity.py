import unittest
from unittest.mock import patch, Mock
import cartpole_host as host
from low_speed_probe import Link, Abort

class ValidityTest(unittest.TestCase):
    def rig(self):
        with patch.object(host.serial, 'Serial'), patch.object(host.time, 'time', side_effect=[0., 1.]):
            r = host.Rig('unused')
            r.ser.write.side_effect = lambda data: len(data)
            return r

    def test_unknown_blocks_nonzero(self):
        r = self.rig()
        r._dispatch('STATE 1 2 0 0')
        with self.assertRaises(RuntimeError): r.send_line('VEL 20')
        r.ser.write.assert_not_called()

    def test_invalid_clears_state_and_recovery_does_not_resume(self):
        r = self.rig()
        r._dispatch('VEL_VALID 1 1')
        r._dispatch('STATE 1 2 0 0')
        r.send_line('VEL 20')
        r._dispatch('VEL_VALID 0 1')
        self.assertIsNone(r.last_state)
        r._dispatch('VEL_VALID 1 1')
        r._dispatch('STATE 1 2 0 0')
        with self.assertRaises(RuntimeError): r.send_line('VEL 20')
        r.send_line('VEL 0')

    def test_malformed_validity_invalidates(self):
        r = self.rig()
        r._dispatch('VEL_VALID 1 1')
        r._dispatch('STATE 1 2 0 0')
        r._dispatch('VEL_VALID 2 1')
        self.assertIsNone(r.last_state)
        with self.assertRaises(RuntimeError): r.send_line('VEL 20')

    def test_link_invalid_and_recovery_same_batch_latches(self):
        ser = Mock(); ser.write.side_effect=lambda x:len(x)
        link = Link(ser, clock=lambda:1.)
        link.aligned = True
        ser.read.return_value=b'VEL_VALID 1 1\nSTATE 1 2 0 0\n'
        link.poll(); link.send('VEL 20')
        ser.read.return_value=b'VEL_VALID 0 1\nVEL_VALID 1 1\nSTATE 1 2 0 0\n'
        with self.assertRaises(Abort): link.poll()
        with self.assertRaises(Abort): link.send('VEL 20')
        link.send('VEL 0')

    def test_link_unknown_state_not_accepted(self):
        ser=Mock(); ser.read.return_value=b'\nSTATE 1 2 0 0\n'
        link=Link(ser); link.poll()
        self.assertIsNone(link.state)
        with self.assertRaises(Abort): link.send('VEL 20')

class ValidityHeartbeatTest(unittest.TestCase):
    def test_stale_heartbeat_latches_even_after_recovery(self):
        from velocity_validity import VelocityValidity
        now = [0.]
        v = VelocityValidity(lambda: now[0])
        v.update(['VEL_VALID', '1', '1']); v.command('VEL 20')
        now[0] = .301
        with self.assertRaises(RuntimeError): v.require()
        v.update(['VEL_VALID', '1', '1'])
        with self.assertRaises(RuntimeError): v.require()

    def test_initial_invalid_can_recover_before_motion(self):
        from velocity_validity import VelocityValidity
        v = VelocityValidity(lambda: 0.)
        v.update(['VEL_VALID', '0', '1'])
        self.assertFalse(v.ready())
        v.update(['VEL_VALID', '1', '1'])
        self.assertTrue(v.ready())

    def test_invalid_during_max_accel_clears_samples(self):
        from collections import deque
        import max_accel_run as m
        r = ValidityTest().rig()
        r.__class__ = m.TestRig
        r._log = None
        r.samples = deque(); r.fault_events = []
        r._dispatch('VEL_VALID 1 1'); r._dispatch('STATE 1 2 0 0')
        self.assertEqual(len(r.samples), 1)
        r.send_line('VEL 20'); r._dispatch('VEL_VALID 1 0')
        self.assertEqual(len(r.samples), 0)
        r._dispatch('VEL_VALID 1 1'); r._dispatch('STATE 1 2 0 0')
        self.assertEqual(len(r.samples), 0)

    def test_malformed_then_state_must_not_repopulate(self):
        r = ValidityTest().rig()
        r._dispatch('VEL_VALID 1 1'); r._dispatch('STATE 1 2 0 0')
        r._dispatch('VEL_VALID 1'); r._dispatch('STATE 1 2 0 0')
        self.assertIsNone(r.last_state)

    def test_late_heartbeat_cannot_hide_gap(self):
        from velocity_validity import VelocityValidity
        now=[0.]; v=VelocityValidity(lambda:now[0])
        v.update(['VEL_VALID','1','1']); v.command('VEL 20')
        now[0]=.4
        v.update(['VEL_VALID','1','1'])
        self.assertFalse(v.ready())

class RunInvalidationTest(unittest.TestCase):
    def test_accel_run_invalid_during_config_cannot_recover(self):
        from test_accel_probe import Rig, args
        from accel_probe import execute
        class InvalidConfig(Rig):
            def write(self, data):
                result = super().write(data)
                if data.startswith(b'CONFIG VEL_MAX'):
                    self.rx += b'VEL_VALID 0 1\nVEL_VALID 1 1\n'
                return result
        f=InvalidConfig(); link=Link(f,f.clock,f.sleep)
        with self.assertRaises(Abort): execute(link,args())
        self.assertNotIn('VEL 400',f.writes)

class HostFailureTest(unittest.TestCase):
    def test_active_unknown_latches_and_clears_both_caches(self):
        from collections import deque
        import max_accel_run as m
        for line in ('VEL_VALI 0 1', 'STATE 1 bad 0 0', 'MODE READY', 'OK VALUE bad'):
            with self.subTest(line=line):
                r=ValidityTest().rig(); r.__class__=m.TestRig
                r._log=None; r.samples=deque(); r.fault_events=[]
                r._dispatch('VEL_VALID 1 1'); r._dispatch('STATE 1 2 0 0')
                r.send_line('VEL 20')
                with patch('builtins.print') as output:
                    r._dispatch(line)
                output.assert_not_called()
                self.assertIsNone(r.last_state); self.assertEqual(len(r.samples),0)
                with self.assertRaises(RuntimeError): r.send_line('VEL 20')
                r.send_line('VEL 0'); r.send_line('DISABLE')

    def test_serial_writes_are_bounded_without_flush(self):
        with patch.object(host.serial,'Serial') as factory, patch.object(host.time,'time',side_effect=[0.,1.]):
            r=host.Rig('unused')
        self.assertEqual(factory.call_args.kwargs['write_timeout'], .02)
        r.ser.write.return_value=6
        r.send_line('VEL 0')
        r.ser.flush.assert_not_called()

    def test_partial_serial_write_fails(self):
        r=ValidityTest().rig(); r.ser.write.side_effect=None; r.ser.write.return_value=2
        with self.assertRaises(RuntimeError): r.send_line('VEL 0')

    def test_handler_stops_before_output(self):
        from types import SimpleNamespace
        events=[]; r=Mock(); r.velocity_validity=SimpleNamespace(active=True)
        r.send_line.side_effect=lambda cmd:events.append(cmd)
        with patch.object(host,'Rig',return_value=r), patch.object(host,'cmd_query',side_effect=RuntimeError('invalid')), patch.object(host.sys,'argv',['tool','--port','unused','query']), patch('builtins.print',side_effect=lambda *args:events.append('print')):
            with self.assertRaises(SystemExit) as result: host.main()
        self.assertEqual(result.exception.code,1)
        self.assertEqual(events[0],'VEL 0')

    def test_state_does_not_display_stale_cached_position(self):
        import contextlib, io
        from types import SimpleNamespace
        r=ValidityTest().rig(); r.last_state=['123','2','0','0']; r.state_received_at=0.
        with patch.object(r,'pump'), patch.object(host.time,'time',side_effect=[0.,0.,1.,1.]), patch.object(host.time,'monotonic',return_value=1.), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(host.cmd_state(r,SimpleNamespace(secs=1.)),1)
        self.assertNotIn('x_um',out.getvalue())

    def test_pump_aborts_before_printing_later_lines(self):
        r=ValidityTest().rig()
        r._dispatch('VEL_VALID 1 1'); r._dispatch('STATE 1 2 0 0'); r.send_line('VEL 20')
        r.ser.read.return_value=b'VEL_VALI 0 1\nMODE READY NONE\n'
        with patch.object(host.time,'time',side_effect=[0.,0.,1.]), patch('builtins.print') as output:
            with self.assertRaises(RuntimeError): r.pump(.1)
        output.assert_not_called()

    def test_test_rig_pump_surfaces_experiment_abort(self):
        from collections import deque
        import max_accel_run as m
        r=ValidityTest().rig(); r.__class__=m.TestRig
        r._log=None; r.samples=deque(); r.fault_events=[]
        r._dispatch('VEL_VALID 1 1'); r._dispatch('STATE 1 2 0 0'); r.send_line('VEL 20')
        r.ser.read.return_value=b'VEL_VALI 0 1\n'
        with patch.object(host.time,'time',side_effect=[0.,0.,1.]):
            with self.assertRaises(m.ExperimentAborted): r.pump(.1)
