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
    def test_v2_hardware_fields(self):
        row = 'SLT2 8 ROW 0 ' + ' '.join(str(i) for i in range(30)) + '\n'
        port = Serial([b'SLT2 8 BEGIN 1 4\n', row.encode(), b'SLT2 8 END 1\n'])
        result = capture.collect(port)
        self.assertEqual(result['version'], 2)
        self.assertEqual(result['samples'][0]['pcnt_count'], 21)
        self.assertEqual(result['samples'][0]['en_level'], 28)
    def test_v3_same_sample_frame(self):
        values = list(range(30)) + [7, 1, 0, 0, 1, 2, 7, 255]
        row = 'SLT3 9 ROW 0 ' + ' '.join(map(str, values)) + '\n'
        result = capture.collect(Serial([b'SLT3 9 BEGIN 1 5\n', row.encode(), b'SLT3 9 END 1\n']))
        sample = result['samples'][0]
        self.assertEqual(result['version'], 3)
        self.assertEqual(sample['encoder_status'], 7)
        self.assertEqual(sample['frame_valid'], 1)
        self.assertEqual(sample['spi_rx5'], 255)
        self.assertEqual(sample['sample_us'], 1)

    def test_mixed_versions_rejected(self):
        with self.assertRaises(ValueError):
            capture.collect(Serial([b'SLT2 8 BEGIN 1 4\n', b'SLT1 8 END 1\n']))
    def test_incomplete(self):
        with self.assertRaises(ValueError):
            capture.collect(Serial([b'SLT1 7 BEGIN 1 3\n', b'SLT1 7 END 1\n']))
    def test_busy(self):
        with self.assertRaises(RuntimeError):
            capture.collect(Serial([b'ERR STEPLOSS_BUSY\n']))

if __name__ == '__main__':
    unittest.main()
