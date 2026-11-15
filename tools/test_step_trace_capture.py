import unittest
from step_trace_capture import Capture
ROW = 'SLT4 ROW 1 0 100 90 91 92 10 20 5 100 0 1 1 1 1'
class TestCapture(unittest.TestCase):
    def test_valid(self):
        c=Capture(); c.feed('SLT4 HEADER 1 2 1 0 1'); c.feed(ROW)
        r=c.feed('SLT4 END 1 1'); self.assertEqual(r['samples'][0]['c_um'],20)
    def test_missing(self):
        c=Capture(); c.feed('SLT4 HEADER 1 2 1 0 1')
        with self.assertRaises(ValueError): c.feed('SLT4 END 1 1')
    def test_mixed(self):
        c=Capture(); c.feed('SLT4 HEADER 1 2 1 0 1')
        with self.assertRaises(ValueError): c.feed(ROW.replace('ROW 1','ROW 2'))
    def test_cap(self):
        with self.assertRaises(ValueError): Capture().feed('SLT4 HEADER 1 2 161 32 1')
    def test_background(self):
        self.assertIsNone(Capture().feed('EVENT STEP_LOSS 1 2 100'))
    def test_error(self):
        with self.assertRaises(ValueError): Capture().feed('ERR STEPTRACE_BUSY')

class TestCollect(unittest.TestCase):
    def test_fragmented_serial_read_only_query(self):
        from step_trace_capture import collect
        class SerialFake:
            def __init__(self):
                self.data = bytearray(('SLT4 HEADER 1 2 1 0 1\n' + ROW + '\nSLT4 END 1 1\n').encode())
                self.sent = []
            def read_until(self, end): return b'partial STATE\n'
            def write(self, data): self.sent.append(data); return len(data)
            @property
            def in_waiting(self): return len(self.data)
            def read(self, count):
                out = bytes(self.data[:3]); del self.data[:3]; return out
        serial = SerialFake()
        self.assertEqual(collect(serial)['count'], 1)
        self.assertEqual(serial.sent, [b'STEPTRACE?\n'])
    def test_incomplete_command_write_fails(self):
        from step_trace_capture import collect
        class SerialFake:
            def read_until(self, end): return b'\n'
            def write(self, data): return 0
        with self.assertRaises(ValueError): collect(SerialFake())

if __name__=='__main__': unittest.main()
