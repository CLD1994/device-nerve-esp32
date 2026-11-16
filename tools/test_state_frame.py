"""统一状态帧解析与只读消费者契约。"""
import unittest
import importlib

VALID='STATE 00000001 00000002 3 0000 ffff 4e20 0000 ffffffff 002fefd8 80000000 7fffffff'
INVALID='STATE 00000001 00000002 0 0000 0000 ffff ffff 00000000 00000000 00000000 00000000'
CAPTURES=('step_loss_capture','step_trace_capture','tmc_trace_capture','pole_diag_capture')
class CaptureStateTest(unittest.TestCase):
    def test_ignores_only_new_valid_state(self):
        for module in CAPTURES:
            c=importlib.import_module(module).Capture()
            for line in (VALID,INVALID):
                with self.subTest(module=module):self.assertIsNone(c.feed(line))
    def test_rejects_old_frames(self):
        for module in CAPTURES:
            for line in ('STATE 1 2 3 4','VEL_VALID 1 1','CART_STATE1 100 0'):
                with self.subTest(module=module,line=line),self.assertRaises(ValueError):
                    importlib.import_module(module).Capture().feed(line)
class ParserTest(unittest.TestCase):
    def parse(self,s):
        from state_frame import parse_state_frame
        return parse_state_frame(s)
    def test_valid_signed_and_boundaries(self):
        r=self.parse(VALID)
        self.assertEqual(r,dict(boot=1,tick=2,flags=3,
            cart=dict(seq=0,age_us=20000,x_um=-1,vx_mm_s=-2147483648),
            pole=dict(seq=65535,age_us=0,theta_urad=3141592,vth_mrad_s=2147483647)))
        self.assertEqual(self.parse(VALID.upper()),r)
    def test_invalid_lanes_are_none(self):
        r=self.parse(INVALID);self.assertIsNone(r['cart']);self.assertIsNone(r['pole'])
        p=INVALID.split();p[3]='1';p[6]='0000';self.assertIsNotNone(self.parse(' '.join(p))['cart'])
        p=INVALID.split();p[3]='2';p[7]='0000';self.assertIsNotNone(self.parse(' '.join(p))['pole'])
    def test_other_tag_none(self):self.assertIsNone(self.parse('MODE DISABLED NONE'))
    def test_strict_layout_and_digits(self):
        for s in (VALID+' ', ' '+VALID,VALID+'\n',VALID.replace(' ','\t',1),VALID.replace(' ','  ',1),
                  VALID.replace('00000001','0x000001'),VALID.replace('00000001','０００００００１'),'STATE 1 2 3 4'):
            with self.subTest(s=s),self.assertRaises(ValueError):self.parse(s)
    def test_invalid_flags_age_angle_and_sentinel(self):
        for index,value in ((3,'4'),(6,'4e21'),(7,'ffff'),(9,'002fefd9'),(9,'ffd01027')):
            p=VALID.split();p[index]=value
            with self.subTest(index=index,value=value),self.assertRaises(ValueError):self.parse(' '.join(p))
        for index,value in ((4,'0001'),(5,'0001'),(6,'0000'),(7,'0000'),(8,'00000001'),(9,'00000001'),(10,'00000001'),(11,'00000001')):
            p=INVALID.split();p[index]=value
            with self.subTest(index=index),self.assertRaises(ValueError):self.parse(' '.join(p))

if __name__=='__main__':unittest.main()

class ProbeStateTest(unittest.TestCase):
    def test_new_double_valid_state_updates_once(self):
        from probe_link import Link
        class Port:
            data=(VALID+'\n').encode()
            def read(self,n):return self.data
        r=Link(Port(),clock=lambda:1);r.aligned=True;r.poll()
        self.assertEqual(r.state,(-1,3141592,-2147483648,2147483647))
        self.assertEqual(r.states,1);r.poll();self.assertEqual(r.states,1)
    def test_invalid_lane_cannot_enable_probe(self):
        from probe_link import Link,Abort
        class Port:
            def read(self,n):return (INVALID+'\n').encode()
        r=Link(Port(),clock=lambda:1);r.aligned=True;r.poll()
        self.assertIsNone(r.state)
        with self.assertRaises(Abort):r.send('VEL 20')
