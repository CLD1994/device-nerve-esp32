import unittest
from unittest.mock import Mock
from tmc_readonly import collect, NAMES

class Capture(unittest.TestCase):
    def port(self, response):
        ser=Mock()
        ser.in_waiting=1
        ser.write.return_value=5
        ser.read.return_value=response
        return ser
    def test_valid(self):
        ser=self.port(b''.join(f'TMC1 {n} 1 196 1 2\n'.encode() for n in NAMES)+b'TMC1 END\n')
        self.assertEqual(set(collect(ser)),NAMES)
        ser.write.assert_called_once_with(b'TMC?\n')
        ser.flush.assert_not_called()
    def test_invalid_not_zero(self):
        ser=self.port(b''.join(f'TMC1 {n} 0 0 1 2\n'.encode() for n in NAMES)+b'TMC1 END\n')
        self.assertTrue(all(r['raw'] is None for r in collect(ser).values()))
    def test_incomplete_busy_short(self):
        for data in [b'TMC1 END\n',b'ERR TMC_BUSY\n',b'TMC1 GCONF 2 0 1 2\n']:
            with self.assertRaises(ValueError):collect(self.port(data))
        ser=self.port(b'');ser.write.return_value=2
        with self.assertRaises(ValueError):collect(ser)

if __name__=='__main__':unittest.main()
