import unittest
from test_step_trace_capture import Serial
from encoder_read_compare import collect
class CompareTest(unittest.TestCase):
    def test_read_only_complete(self):
        port=Serial([b'ERT1 START 4000\n',b'ERT1 BEGIN 1\n',
                     b'ERT1 ROW 0 1 100 200 23 7 4 4 1 1 0 0 191 4\n',b'ERT1 END 1\n'])
        r=collect(port,announce=lambda s:None)
        self.assertEqual(port.writes,[b'ENCODERTEST?\n'])
        self.assertEqual(r['samples'][0]['phase'],1)
        self.assertEqual(r['samples'][0]['reg006'],4)
    def test_busy(self):
        with self.assertRaises(RuntimeError): collect(Serial([b'ERR ENCODERTEST_BUSY\n']))
    def test_incomplete(self):
        with self.assertRaises(ValueError):
            collect(Serial([b'ERT1 START 4000\n',b'ERT1 BEGIN 1\n',b'ERT1 END 1\n']),announce=lambda s:None)
if __name__=='__main__':unittest.main()
