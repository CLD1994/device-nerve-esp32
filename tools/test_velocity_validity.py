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


def frame(seq=1, tick=2000, flags=3, boot=1, age=0, pole_seq=None):
    return dict(boot=boot,tick=tick,flags=flags,
        cart=dict(seq=seq,age_us=age,x_um=1,vx_mm_s=0) if flags&1 else None,
        pole=dict(seq=seq if pole_seq is None else pole_seq,age_us=age,theta_urad=2,vth_mrad_s=0) if flags&2 else None)


def wire(seq=1,tick=2000,flags=3):
    return state_line(x=1,theta=2,vx=0,vth=0,boot=1,tick=tick,seq=seq,
                      flags=flags).decode().rstrip('\n')


class IdentityValidityTest(unittest.TestCase):
    def setUp(self):
        self.now=[123456.]
        self.v=VelocityValidity(lambda:self.now[0])
    def advance(self,s):self.now[0]+=s
    def test_initial_invalid_recovers_before_motion(self):
        self.assertFalse(self.v.update(frame(flags=0)))
        self.assertTrue(self.v.update(frame(2,4000)))
    def test_cart_requirement_independent_of_pole(self):
        v=VelocityValidity(lambda:0.,required_mask=1)
        self.assertTrue(v.update(frame(flags=1)))
        self.assertFalse(self.v.update(frame(flags=1)))
    def test_joint_requires_both_new_samples(self):
        self.assertTrue(self.v.update(frame()))
        self.advance(.002)
        f=frame(2,4000,pole_seq=1);f['pole']['age_us']=2000
        self.assertFalse(self.v.update(f))
        f=frame(2,6000,pole_seq=2);f['cart']['age_us']=2000
        self.assertTrue(self.v.update(f))
    def test_duplicate_does_not_refresh(self):
        f=frame();self.v.update(f);stamp=self.v.received_at
        self.advance(.05);self.assertFalse(self.v.update(f))
        self.assertEqual(self.v.received_at,stamp)
        self.advance(.051);self.assertFalse(self.v.ready())
    def test_new_tick_same_sample_does_not_refresh(self):
        self.v.update(frame());stamp=self.v.received_at
        self.advance(.01);self.assertFalse(self.v.update(frame(1,12000,age=10000)))
        self.assertEqual(stamp,self.v.received_at)
    def test_sequence_wrap_is_new(self):
        self.v.update(frame(65535));self.advance(.002)
        self.assertTrue(self.v.update(frame(0,4000)))
    def test_tick_wrap_is_forward(self):
        self.v.update(frame(1,0xfffffff0));self.advance(.000032)
        self.assertTrue(self.v.update(frame(2,0x10)))
    def test_boot_change_latches(self):
        self.v.update(frame())
        with self.assertRaises(RuntimeError):self.v.update(frame(2,4000,boot=2))
        self.assertTrue(self.v.failed)
    def test_seq_reverse_and_half_range_rejected(self):
        for seq in (0,32769):
            with self.subTest(seq=seq):
                v=VelocityValidity(lambda:0.);v.update(frame())
                with self.assertRaises(RuntimeError):v.update(frame(seq,4000))
    def test_tick_reverse_and_half_range_rejected(self):
        for tick in (1999,2000+0x80000000):
            with self.subTest(tick=tick):
                v=VelocityValidity(lambda:0.);v.update(frame())
                with self.assertRaises(RuntimeError):v.update(frame(2,tick))
    def test_same_tick_contradiction_rejected(self):
        self.v.update(frame())
        with self.assertRaises(RuntimeError):self.v.update(frame(2))
    def test_same_seq_changed_measurement_rejected(self):
        self.v.update(frame());f=frame(1,4000);f['cart']['x_um']=2
        with self.assertRaises(RuntimeError):self.v.update(f)
    def test_late_frame_does_not_unlatch(self):
        self.v.update(frame());self.v.command('VEL 20');self.advance(.101)
        self.assertFalse(self.v.update(frame(2,103000)))
        self.assertTrue(self.v.failed)
        with self.assertRaises(RuntimeError):self.v.require()
        self.v.command('VEL 0')
    def test_invalid_during_motion_latches(self):
        self.v.update(frame());self.v.command('VEL 20')
        self.assertFalse(self.v.update(frame(2,4000,flags=1)))
        self.assertFalse(self.v.update(frame(3,6000)))
        self.assertTrue(self.v.failed)
    def test_source_age_plus_host_age_not_absolute_clock(self):
        self.v.update(frame(tick=7,age=20000));self.advance(.03)
        self.assertAlmostEqual(self.v.age(),.05)
        self.assertTrue(self.v.ready())
    def test_relative_queue_growth_added(self):
        self.v.update(frame());self.advance(.05)
        self.v.update(frame(2,12000,age=9999))
        self.assertAlmostEqual(self.v.relative_backlog_s,.04)
        self.assertAlmostEqual(self.v.age(),.049999)
    def test_stopped_copy_preserves_identity_not_motion_permission(self):
        self.v.update(frame());self.v.command('VEL 20');self.v.failed=True
        out=self.v.stopped_copy();self.assertFalse(out.ready())
        self.assertFalse(out.update(frame()))
        self.assertTrue(out.update(frame(2,4000)))
        self.assertTrue(self.v.failed)
        with self.assertRaises(RuntimeError):self.v.command('VEL 20')
    def test_new_sequence_requires_strictly_new_sample_time(self):
        for age in (2000, 20000):
            with self.subTest(age=age):
                v=VelocityValidity(lambda:0.);v.update(frame(100,100000))
                with self.assertRaises(RuntimeError):v.update(frame(101,102000,age=age))
                self.assertTrue(v.failed)
    def test_duplicate_sequence_requires_same_sample_time(self):
        for age in (0, 2001):
            with self.subTest(age=age):
                v=VelocityValidity(lambda:0.);v.update(frame(100,100000))
                with self.assertRaises(RuntimeError):v.update(frame(100,102000,age=age))
    def test_sample_watermark_survives_invalid_and_stopped_copy(self):
        self.v.update(frame(100,100000))
        self.v.update(frame(101,101000,flags=0))
        out=self.v.stopped_copy()
        with self.assertRaises(RuntimeError):out.update(frame(101,102000,age=20000))
        self.assertFalse(self.v.failed)
    def test_sample_time_unwrap_with_sequence_wrap(self):
        self.v.update(frame(65535,0xfffffff0,age=5))
        self.advance(.000032)
        self.assertTrue(self.v.update(frame(0,0x10,age=5)))
        self.advance(.000010)
        self.assertFalse(self.v.update(frame(0,0x1a,age=15)))
    def test_independent_lane_sample_watermarks(self):
        self.v.update(frame(100,100000))
        f=frame(101,102000,pole_seq=100);f['pole']['age_us']=2000
        self.assertFalse(self.v.update(f))
        f=frame(101,104000,pole_seq=101);f['cart']['age_us']=2000
        self.assertTrue(self.v.update(f))
        f=frame(102,106000,pole_seq=102);f['pole']['age_us']=3000
        with self.assertRaises(RuntimeError):self.v.update(f)

    def test_old_validity_message_rejected(self):
        with self.assertRaises(RuntimeError):self.v.update(['VEL_VALID','1','1'])


class HostFailureTest(unittest.TestCase):
    def test_old_state_does_not_enable_motion(self):
        rig,port,_,_=session(host.Rig);receive(rig,port,'STATE 1 2 0 0')
        with self.assertRaises(RuntimeError):rig.send_line('VEL 20')
        self.assertEqual(port.writes,[])
    def test_invalid_does_not_resume_after_good_frame(self):
        rig,port,_,_=session(host.Rig);receive(rig,port,wire());rig.send_line('VEL 20')
        for line in (wire(2,4000,flags=0),wire(3,6000)):
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
