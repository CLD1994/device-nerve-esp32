import unittest
import step_trace_capture as capture

class Serial:
    def __init__(self, lines):
        self.lines = iter(lines)
        self.writes = []
    def write(self, data):
        self.writes.append(data)
        return len(data)
    def readline(self):
        return next(self.lines)

class TraceTest(unittest.TestCase):
    def test_complete(self):
        row = 'SLT1 7 ROW 0 ' + ' '.join(str(i) for i in range(21)) + '\n'
        port = Serial([b'STATE 0 0 0 0\n', b'SLT1 7 BEGIN 1 3\n', row.encode(), b'SLT1 7 END 1\n'])
        result = capture.collect(port)
        self.assertEqual(port.writes, [b'STEPTRACE?\n'])
        self.assertEqual(result['samples'][0]['wdt_expired_count'], 20)
        self.assertEqual(result['event_id'], 7)
    def test_incomplete(self):
        with self.assertRaises(ValueError):
            capture.collect(Serial([b'SLT1 7 BEGIN 1 3\n', b'SLT1 7 END 1\n']))
    def test_busy(self):
        with self.assertRaises(RuntimeError):
            capture.collect(Serial([b'ERR STEPLOSS_BUSY\n']))

if __name__ == '__main__':
    unittest.main()
