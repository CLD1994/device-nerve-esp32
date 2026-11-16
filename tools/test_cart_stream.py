"""小车独立观测帧的协议与消费者回归。"""
import unittest
import importlib

CAPTURES=('step_loss_capture','step_trace_capture','tmc_trace_capture','pole_diag_capture')
VALID=('CART_STATE1 100 90 4 1 -12 34','CART_STATE1 100 0')

class ConsumerTest(unittest.TestCase):
    def test_captures_ignore_valid_cart_frames(self):
        for module in CAPTURES:
            c=importlib.import_module(module).Capture()
            for line in VALID:
                with self.subTest(module=module,line=line):self.assertIsNone(c.feed(line))
    def test_captures_reject_malformed_cart_frames(self):
        for module in CAPTURES:
            with self.subTest(module=module),self.assertRaises(ValueError):
                importlib.import_module(module).Capture().feed('CART_STATE1 100 101 4 1 0 0')
    def test_probe_does_not_replace_state_or_refresh_age(self):
        from probe_link import Link
        class Port:
            data=('\n'.join(VALID)+'\n').encode()
            def read(self,n):data=self.data;self.data=b'';return data
        r=Link(Port(),clock=lambda:10);r.aligned=True;r.state=(1,2,3,4);r.received_at=2
        r.poll()
        self.assertEqual(r.state,(1,2,3,4));self.assertEqual(r.received_at,2)
        self.assertEqual(r.states,0);self.assertEqual(r.batch,[])
    def test_probe_rejects_bad_cart_frame(self):
        from probe_link import Link,Abort
        class Port:
            def read(self,n):return b'CART_STATE1 100 2\n'
        r=Link(Port());r.aligned=True
        with self.assertRaises(Abort):r.poll()

class ParserTest(unittest.TestCase):
    def parse(self,line):
        from cart_stream import parse_cart_state
        return parse_cart_state(line)
    def test_valid_and_invalid_are_distinct(self):
        self.assertEqual(self.parse(VALID[0]),dict(device_us=100,sample_us=90,seq=4,valid=True,x_um=-12,vx_mm_s=34))
        self.assertEqual(self.parse(VALID[1]),dict(device_us=100,sample_us=None,seq=None,valid=False,x_um=None,vx_mm_s=None))
        self.assertIsNone(self.parse('STATE 1 2 3 4'))
    def test_integer_extremes(self):
        r=self.parse('CART_STATE1 9223372036854775807 9223372036854775807 18446744073709551615 1 -2147483648 2147483647')
        self.assertEqual(r['seq'],2**64-1)
    def test_reject_bad_counts_ascii_ranges_and_clock_order(self):
        for line in ['CART_STATE1','CART_STATE1 1 1','CART_STATE1 -1 0','CART_STATE1 9223372036854775808 0',
                     'CART_STATE1 1 2 0 1 0 0','CART_STATE1 1 -1 0 1 0 0',
                     'CART_STATE1 1 0 18446744073709551616 1 0 0','CART_STATE1 1 0 0 0 0 0',
                     'CART_STATE1 1 0 0 1 2147483648 0','CART_STATE1 1 0 0 1 0 -2147483649',
                     'CART_STATE1 １ 0','CART_STATE1 +1 0','CART_STATE1 1 0 extra',
                     'CART_STATE1 '+'0'*150+' 0']:
            with self.subTest(line=line),self.assertRaises(ValueError):self.parse(line)

if __name__=='__main__':unittest.main()
