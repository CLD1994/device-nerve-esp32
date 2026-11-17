"""十进制状态帧解析与只读消费者契约。"""
import unittest
import importlib
VALID='STATE 3 -1 3141592 -2147483648 2147483647'
INVALID='STATE 0 0 0 0 0'
CAPTURES=('step_loss_capture','step_trace_capture')
class CaptureStateTest(unittest.TestCase):
    def test_ignores_only_new_valid_state(self):
        for module in CAPTURES:
            for line in (VALID,INVALID):
                with self.subTest(module=module):self.assertIsNone(importlib.import_module(module).Capture().feed(line))
    def test_rejects_old_frames(self):
        for module in CAPTURES:
            for line in ('STATE 1 2 3 4','VEL_VALID 1 1','CART_STATE1 100 0','STATE 00000002 3 4e20 0000 ffffffff 002fefd8 80000000 7fffffff'):
                with self.subTest(module=module,line=line),self.assertRaises(ValueError):importlib.import_module(module).Capture().feed(line)
class ParserTest(unittest.TestCase):
    def parse(self,s):
        from state_frame import parse_state_frame
        return parse_state_frame(s)
    def test_exact_wire_bounds_and_removed_fields(self):
        from state_test_support import state_line
        shortest=state_line(flags=0);longest=state_line(-2147483648,-3141592,-2147483648,-2147483648)
        self.assertEqual(len(shortest),16);self.assertEqual(len(longest),53)
        self.assertEqual(len(longest.split()),6)
        self.assertEqual(set(self.parse(longest.decode().rstrip('\n'))),{'flags','cart','pole'})
    def test_valid_signed_and_boundaries(self):
        self.assertEqual(self.parse(VALID),dict(flags=3,
            cart=dict(x_um=-1,vx_mm_s=-2147483648),pole=dict(theta_urad=3141592,vth_mrad_s=2147483647)))
    def test_invalid_lanes_are_none(self):
        r=self.parse(INVALID);self.assertIsNone(r['cart']);self.assertIsNone(r['pole'])
        self.assertIsNotNone(self.parse('STATE 1 0 0 0 0')['cart'])
        self.assertIsNotNone(self.parse('STATE 2 0 0 0 0')['pole'])
    def test_negative_zero_rejected_in_every_measurement_slot(self):
        for i in range(2,6):
            parts=['STATE','3','0','0','0','0'];parts[i]='-0'
            with self.subTest(slot=i),self.assertRaises(ValueError):self.parse(' '.join(parts))
    def test_other_tag_none(self):self.assertIsNone(self.parse('MODE DISABLED NONE'))
    def test_strict_layout_and_digits(self):
        for s in (VALID+' ',' '+VALID,VALID+'\n',VALID.replace(' ','\t',1),VALID.replace(' ','  ',1),
                  'STATE 3 +1 0 0 0','STATE 3 01 0 0 0','STATE 3 -0 0 0 0','STATE 3 １ 0 0 0','STATE 3 ff 0 0 0','STATE 3 0x01 0 0 0'):
            with self.subTest(s=s),self.assertRaises(ValueError):self.parse(s)
    def test_invalid_flags_angle_int32_and_sentinel(self):
        for s in ('STATE 4 0 0 0 0','STATE 3 2147483648 0 0 0','STATE 3 -2147483649 0 0 0',
                  'STATE 3 0 3141593 0 0','STATE 3 0 -3141593 0 0','STATE 0 1 0 0 0',
                  'STATE 0 0 1 0 0','STATE 0 0 0 1 0','STATE 0 0 0 0 1'):
            with self.subTest(s=s),self.assertRaises(ValueError):self.parse(s)
class ProbeStateTest(unittest.TestCase):
    def test_repeated_values_are_new_received_observations(self):
        from probe_link import Link
        class Port:
            def read(self,n):return (VALID+'\n').encode()
        r=Link(Port(),clock=lambda:1);r.aligned=True;r.poll()
        self.assertEqual(r.state,(-1,3141592,-2147483648,2147483647))
        self.assertEqual(r.states,1);r.poll();self.assertEqual(r.states,2)
    def test_invalid_lane_cannot_enable_probe(self):
        from probe_link import Link,Abort
        class Port:
            def read(self,n):return (INVALID+'\n').encode()
        r=Link(Port(),clock=lambda:1);r.aligned=True;r.poll();self.assertIsNone(r.state)
        with self.assertRaises(Abort):r.send('VEL 20')
if __name__=='__main__':unittest.main()

class ByteBoundaryTest(unittest.TestCase):
    def test_probe_rejects_extra_cr_but_accepts_crlf(self):
        from probe_link import Link, Abort
        from types import SimpleNamespace
        for ending in (b'\r\n',b'\r\r\n'):
            link=Link(SimpleNamespace(read=lambda n:b'\nSTATE 3 1 2 3 4'+ending),clock=lambda:0.)
            if ending==b'\r\n':
                link.poll();self.assertEqual(link.states,1)
            else:
                with self.assertRaises(Abort):link.poll()

    def test_capture_byte_boundary_preserves_extra_cr(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        for module in CAPTURES:
            for ending in (b'\r\n',b'\r\r\n'):
                data=b'STATE 3 1 2 3 4'+ending
                stream=SimpleNamespace(read_until=lambda x:b'\n',write=lambda b:len(b),
                    in_waiting=len(data),read=lambda n:data)
                parser=importlib.import_module(module)
                received=[]
                def feed(line):
                    received.append(line)
                    parse_state_frame=importlib.import_module('state_frame').parse_state_frame
                    parse_state_frame(line)
                    return {'done':True}
                with patch.object(parser.Capture,'feed',side_effect=feed):
                    if ending==b'\r\n':self.assertEqual(parser.collect(stream),{'done':True})
                    else:
                        with self.assertRaises(ValueError):parser.collect(stream)
