"""统一STATE身份/时效契约与字节入口门禁；不模拟旧协议兼容。"""
import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
import cartpole_host as host
import max_accel_run as accel
from host_test_support import session, receive
from velocity_validity import VelocityValidity
from state_test_support import state_line


def frame(flags=3):
    return dict(flags=flags,cart=dict(x_um=1,vx_mm_s=0) if flags&1 else None,
                pole=dict(theta_urad=2,vth_mrad_s=0) if flags&2 else None)
def wire(flags=3):
    return state_line(x=1,theta=2,flags=flags).decode().rstrip('\n')
class IdentityValidityTest(unittest.TestCase):
    def setUp(self):
        self.now=[123456.];self.v=VelocityValidity(lambda:self.now[0])
    def advance(self,s):self.now[0]+=s
    def test_initial_invalid_recovers_before_motion(self):
        self.assertFalse(self.v.update(frame(0)));self.assertTrue(self.v.update(frame()))
    def test_cart_requirement_independent_of_pole(self):
        v=VelocityValidity(lambda:0.,required_mask=1)
        self.assertTrue(v.update(frame(1)));self.assertFalse(self.v.update(frame(1)))
    def test_joint_requires_both_valid_lanes(self):
        self.assertFalse(self.v.update(frame(1)));self.assertFalse(self.v.update(frame(2)))
        self.assertTrue(self.v.update(frame()))
    def test_repeated_values_refresh_receive_time(self):
        self.v.update(frame());self.advance(.05)
        self.assertTrue(self.v.update(frame()));self.assertEqual(self.v.received_at,self.now[0])
        self.assertEqual(self.v.age(),0)
    def test_only_receive_age_no_source_age_or_identity_claim(self):
        self.v.update(frame());self.advance(.03);self.assertAlmostEqual(self.v.age(),.03)
        self.assertFalse(hasattr(self.v,'tick'));self.assertFalse(hasattr(self.v,'boot'))
    def test_late_frame_does_not_unlatch(self):
        self.v.update(frame());self.v.command('VEL 20');self.advance(.101)
        self.assertFalse(self.v.update(frame()));self.assertTrue(self.v.failed)
        with self.assertRaises(RuntimeError):self.v.require()
        self.v.command('VEL 0')
    def test_invalid_during_motion_latches(self):
        self.v.update(frame());self.v.command('VEL 20')
        self.assertFalse(self.v.update(frame(1)));self.assertFalse(self.v.update(frame()))
        self.assertTrue(self.v.failed)
    def test_stopped_copy_needs_new_receive_not_distinct_sample(self):
        self.v.update(frame());self.v.command('VEL 20');self.v.failed=True
        out=self.v.stopped_copy();self.assertFalse(out.ready());self.assertTrue(out.update(frame()))
        self.assertTrue(self.v.failed)
        with self.assertRaises(RuntimeError):self.v.command('VEL 20')
    def test_expiry_boundary_and_clock_regression(self):
        v=VelocityValidity(lambda:self.now[0]);self.now[0]=0;v.update(frame())
        self.now[0]=.1;self.assertTrue(v.ready());self.now[0]=.100001;self.assertFalse(v.ready())
        self.now[0]=-.001;self.assertFalse(v.ready())
    def test_old_validity_message_rejected(self):
        with self.assertRaises(RuntimeError):self.v.update(['VEL_VALID','1','1'])


class HostFailureTest(unittest.TestCase):
    def test_old_state_does_not_enable_motion(self):
        rig,port,_,_=session(host.Rig);receive(rig,port,'STATE 1 2 0 0')
        with self.assertRaises(RuntimeError):rig.send_line('VEL 20')
        self.assertEqual(port.writes,[])
    def test_invalid_does_not_resume_after_good_frame(self):
        rig,port,_,_=session(host.Rig);receive(rig,port,wire());rig.send_line('VEL 20')
        for line in (wire(flags=0),wire()):
            with self.assertRaises(RuntimeError):receive(rig,port,line)
        self.assertIsNone(rig.last_state)
        with self.assertRaises(RuntimeError):rig.send_line('VEL 20')
        rig.send_line('VEL 0');self.assertEqual(port.writes,[b'VEL 20\n',b'VEL 0\n'])
    def test_partial_lines_survive_boundary(self):
        rig,port,_,_=session(host.Rig);row=wire().encode()
        port.feed(row[:12]);rig.pump(.005);self.assertIsNone(rig.last_state)
        port.feed(row[12:]+b'\n');rig.pump(.005);rig.send_line('VEL 20')
        self.assertEqual(rig.last_state,['1','2','0','0']);self.assertEqual(rig.unknown_count,0)
    def test_unknown_latches_and_clears_test_rig(self):
        for line in ('VEL_VALID 1 1','STATE bad','MODE READY','OK VALUE bad'):
            with self.subTest(line=line):
                rig,port,_,messages=session(accel.TestRig);receive(rig,port,wire());rig.send_line('VEL 20')
                with self.assertRaises(accel.ExperimentAborted):receive(rig,port,line)
                self.assertEqual(messages,[]);self.assertIsNone(rig.last_state_tuple())
                with self.assertRaises(RuntimeError):rig.send_line('VEL 20')
                rig.send_line('VEL 0');rig.send_line('DISABLE')
    def test_serial_write_bounded_no_flush(self):
        rig,port,_,_=session(host.Rig);self.assertEqual(port.open_options,('memory',460800,.2,.02))
        rig.send_line('VEL 0');self.assertEqual(port.flush_count,0)
        port.write_limit=2
        with self.assertRaises(RuntimeError):rig.send_line('VEL 0')
    def test_handler_zero_before_print(self):
        events=[];rig=Mock(spec=host.Rig);rig.velocity_validity=SimpleNamespace(active=True)
        rig.send_line.side_effect=lambda cmd:events.append(cmd)
        with patch.object(host,'Rig',return_value=rig),patch.object(host,'cmd_query',side_effect=RuntimeError('invalid')),patch.object(host.sys,'argv',['tool','--port','unused','query']),patch('builtins.print',side_effect=lambda *a:events.append('print')):
            with self.assertRaises(SystemExit) as result:host.main()
        self.assertEqual(result.exception.code,1);self.assertEqual(events[0],'VEL 0')
    def test_cached_state_expiry_not_displayed(self):
        rig,port,clock,_=session(host.Rig);receive(rig,port,wire());clock.advance(.2)
        with patch.object(host.time,'time',side_effect=[0.,0.,1.,1.]),contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(host.cmd_state(rig,SimpleNamespace(secs=1.)),1)
        self.assertNotIn('x_um',out.getvalue())
    def test_invalid_prevents_later_mode_output(self):
        rig,port,_,messages=session(host.Rig);receive(rig,port,wire());rig.send_line('VEL 20')
        port.feed(b'VEL_VALID 1 1\nMODE READY NONE\n')
        with self.assertRaises(RuntimeError):rig.pump(.1)
        self.assertEqual(messages,[]);self.assertIsNone(rig.last_mode)
    def test_injected_log_lifetime(self):
        log=io.StringIO();rig,port,_,_=session(accel.TestRig,log_sink=log);receive(rig,port,wire())
        self.assertEqual(rig.last_state_tuple(),(1,0));self.assertIn(wire(),log.getvalue())
        rig.close();self.assertTrue(port.closed);self.assertFalse(log.closed)

if __name__=='__main__':unittest.main()
