from test_state_frame import INVALID as NEW_STATE
import unittest
from unittest.mock import patch
import tmc_trace_capture as tool

BEGIN = 'TMCT1 BEGIN 3 2 1000000 1 3 1 50000 5000000 6000000'
ROWS = ['TMCT1 ROW 3 0 10 900000 902000 0 63',
        'TMCT1 ROW 3 1 11 999000 1001000 1 0',
        'TMCT1 ROW 3 2 12 1050000 1052000 2 0']
END = 'TMCT1 END 3 3'

def captured():
    c=tool.Capture()
    for line in [BEGIN,*ROWS]: c.feed(line)
    return c.feed(END)

class CaptureTests(unittest.TestCase):
    def test_complete_and_failed_raw_not_normal(self):
        r=captured()
        self.assertEqual(r['event_id'],3)
        self.assertEqual(r['samples'][0]['raw'],63)
        self.assertTrue(r['samples'][0]['decoded']['s2vsb'])
        self.assertIsNone(r['samples'][1]['decoded'])
        self.assertIsNone(r['samples'][2]['decoded'])
        self.assertEqual(r['statistics']['busy_count'],1)
        self.assertEqual(r['statistics']['read_error_count'],1)
        self.assertEqual(r['statistics']['sample_interval_us']['max'],99000)
        self.assertEqual(r['statistics']['transaction_duration_us']['max'],2000)
    def test_decode_bits_independently(self):
        for flag,bit in [('otpw',0),('ot',1),('s2ga',2),('s2gb',3),('s2vsa',4),('s2vsb',5),('ola',6),('olb',7),('stealth',30),('stst',31)]:
            with self.subTest(flag=flag):self.assertTrue(tool.decode_status(1<<bit)[flag])
        self.assertEqual(tool.decode_status(31<<16)['cs_actual'],31)
    def test_zero_samples_has_no_normal_claim(self):
        c=tool.Capture();c.feed('TMCT1 BEGIN 1 1 100 2 0 0 50000 5000000 200')
        r=c.feed('TMCT1 END 1 0');self.assertIsNone(r['statistics']['sample_interval_us'])
        self.assertEqual(r['statistics']['valid_count'],0)
    def test_complete_requires_real_time(self):
        with self.assertRaises(ValueError):tool.Capture().feed(BEGIN.replace('6000000','5999999'))
    def test_header_ranges(self):
        for values in ['0 2 1000000 1 3 1 50000 5000000 6000000','3 0 1000000 1 3 1 50000 5000000 6000000','3 2 1000000 3 3 1 50000 5000000 6000000','3 2 1000000 1 143 1 50000 5000000 6000000','3 2 1000000 1 3 4 50000 5000000 6000000','3 2 1000000 1 3 1 0 5000000 6000000']:
            with self.subTest(values=values),self.assertRaises(ValueError):tool.Capture().feed('TMCT1 BEGIN '+values)
    def test_bad_rows(self):
        for row in ['TMCT1 ROW 4 0 10 900000 902000 0 63','TMCT1 ROW 3 1 10 900000 902000 0 63','TMCT1 ROW 3 0 10 902000 900000 0 63','TMCT1 ROW 3 0 10 900000 902000 3 0','TMCT1 ROW 3 0 10 900000 902000 1 3','TMCT1 ROW 3 0 10 900000 902000 0 4294967296']:
            c=tool.Capture();c.feed(BEGIN)
            with self.subTest(row=row),self.assertRaises(ValueError):c.feed(row)
    def test_order_duplicate_and_missing(self):
        with self.assertRaises(ValueError):tool.Capture().feed(ROWS[0])
        c=tool.Capture();c.feed(BEGIN)
        with self.assertRaises(ValueError):c.feed(BEGIN)
        with self.assertRaises(ValueError):c.feed(END)
    def test_sequence_and_time_order(self):
        for row in [ROWS[1].replace('1 11','1 10'),ROWS[1].replace('999000','899000')]:
            c=tool.Capture();c.feed(BEGIN);c.feed(ROWS[0])
            with self.assertRaises(ValueError):c.feed(row)
    def test_equal_timestamp_can_be_pre_or_post(self):
        for pre in (0,1):
            c=tool.Capture();c.feed(f'TMCT1 BEGIN 3 2 1000000 1 1 {pre} 50000 5000000 6000000')
            c.feed('TMCT1 ROW 3 0 1 999000 1000000 0 0')
            self.assertEqual(c.feed('TMCT1 END 3 1')['count'],1)
    def test_rows_respect_time_windows(self):
        c=tool.Capture();c.feed('TMCT1 BEGIN 3 2 3000000 1 1 1 50000 5000000 8000000')
        with self.assertRaises(ValueError):c.feed('TMCT1 ROW 3 0 1 900000 999999 0 0')
        c=tool.Capture();c.feed('TMCT1 BEGIN 3 2 1000000 1 1 0 50000 5000000 6000010')
        with self.assertRaises(ValueError):c.feed('TMCT1 ROW 3 0 1 6000000 6000001 0 0')
    def test_end_identity(self):
        c=tool.Capture();c.feed(BEGIN)
        for row in ROWS:c.feed(row)
        with self.assertRaises(ValueError):c.feed('TMCT1 END 4 3')
        c.feed(END)
        with self.assertRaises(ValueError):c.feed(END)
    def test_background_and_errors(self):
        for line in [NEW_STATE,'MODE DISABLED NONE','EVENT STEP_LOSS 3 2 1000000']:
            self.assertIsNone(tool.Capture().feed(line))
        for line in ['ERR TMCTRACE_BUSY','TMCT2 BEGIN 0','TMCT1 ROW bad','nonsense']:
            with self.assertRaises(ValueError):tool.Capture().feed(line)

class Version2Tests(unittest.TestCase):
    def capture(self, rows):
        c=tool.Capture()
        c.feed(f'TMCT2 BEGIN 3 2 1000000 1 {len(rows)} 0 50000 5000000 6000000')
        for index, fields in enumerate(rows):c.feed(f'TMCT2 ROW 3 {index} {fields}')
        return c.feed(f'TMCT2 END 3 {len(rows)}')
    def test_register_specific_decode_statistics(self):
        r=self.capture(['1 1000000 1001000 0 111 7','2 1001100 1002000 0 1 7',
                        '3 1052000 1053000 1 111 0','4 1053100 1054000 2 1 0'])
        self.assertEqual(r['version'],2)
        self.assertEqual(r['samples'][1]['decoded'],dict(reset=True,drv_err=True,uv_cp=True))
        self.assertNotIn('reset',r['samples'][0]['decoded'])
        self.assertIsNone(r['samples'][2]['decoded'])
        stats=r['statistics']['by_register']
        self.assertEqual(stats['GSTAT']['sample_interval_us']['max'],52000)
        self.assertEqual(stats['DRV_STATUS']['busy_count'],1)
        self.assertEqual(stats['GSTAT']['read_error_count'],1)
        self.assertNotIn('otpw',stats['GSTAT']['asserted_flag_counts'])
        self.assertNotIn('sample_interval_us',r['statistics'])
    def test_same_register_rows_need_not_alternate(self):
        r=self.capture(['1 1000000 1001000 0 1 1','2 1050000 1051000 0 1 1'])
        self.assertEqual(r['statistics']['by_register']['GSTAT']['valid_count'],2)
        self.assertEqual(r['statistics']['by_register']['GSTAT']['asserted_flag_counts']['reset'],2)
        self.assertEqual(r['statistics']['by_register']['DRV_STATUS']['valid_count'],0)
    def test_v2_reg_and_field_validation(self):
        for fields in ['1 1000000 1001000 0 2 7','1 1000000 1001000 0 7',
                       '1 1000000 1001000 1 1 1','1 1000000 1001000 2 111 1']:
            with self.subTest(fields=fields),self.assertRaises(ValueError):self.capture([fields])
    def test_cannot_mix_versions(self):
        for version in (1,2):
            c=tool.Capture();c.feed(f'TMCT{version} BEGIN 3 2 1000000 1 0 0 50000 5000000 6000000')
            with self.assertRaises(ValueError):c.feed(f'TMCT{3-version} END 3 0')
    def test_capacity_depends_on_version(self):
        c=tool.Capture();c.feed('TMCT2 BEGIN 3 2 1000000 1 284 80 50000 5000000 6000000')
        for header in ['TMCT2 BEGIN 3 2 1000000 1 285 80 50000 5000000 6000000',
                       'TMCT2 BEGIN 3 2 1000000 1 284 81 50000 5000000 6000000',
                       'TMCT2 BEGIN 3 2 1000000 1 205 0 50000 5000000 6000000']:
            with self.assertRaises(ValueError):tool.Capture().feed(header)
    def test_empty_register_has_no_validity_claim(self):
        r=self.capture(['1 1000000 1001000 0 111 0'])
        stats=r['statistics']['by_register']['GSTAT']
        self.assertEqual(stats['valid_count'],0)
        self.assertIsNone(stats['sample_interval_us'])

class SerialFake:
    def __init__(self,data):self.data=bytearray(data);self.sent=[]
    def read_until(self,end):return b'partial\n'
    def write(self,data):self.sent.append(data);return len(data)
    @property
    def in_waiting(self):return len(self.data)
    def read(self,count):out=bytes(self.data[:min(count,7)]);del self.data[:len(out)];return out

class CollectTests(unittest.TestCase):
    def test_fragmented_read_only(self):
        ser=SerialFake(('\n'.join([BEGIN,*ROWS,END])+'\n').encode())
        self.assertEqual(tool.collect(ser)['count'],3)
        self.assertEqual(ser.sent,[b'TMCTRACE?\n'])
    def test_v2_fragmented_read_only(self):
        data=b'TMCT2 BEGIN 3 2 1000000 1 1 0 50000 5000000 6000000\nTMCT2 ROW 3 0 1 1000000 1001000 0 1 4\nTMCT2 END 3 1\n'
        ser=SerialFake(data)
        result=tool.collect(ser)
        self.assertEqual(result['version'],2)
        self.assertTrue(result['samples'][0]['decoded']['uv_cp'])
        self.assertEqual(ser.sent,[b'TMCTRACE?\n'])
    def test_short_write(self):
        ser=SerialFake(b'');ser.write=lambda data:0
        with self.assertRaises(ValueError):tool.collect(ser)
    def test_timeout(self):
        with patch.object(tool.time,'monotonic',side_effect=[0,0,20]):
            with self.assertRaises(TimeoutError):tool.collect(SerialFake(b''))
    def test_oversized_line_is_rejected(self):
        ser=SerialFake(b'x'*65537)
        with self.assertRaises(ValueError):tool.collect(ser)
    def test_non_ascii_is_not_silently_skipped(self):
        with self.assertRaises(UnicodeDecodeError):tool.collect(SerialFake(b'\xff\n'))
    def test_invalid_timeout(self):
        for timeout in [0,-1,float('nan'),float('inf')]:
            ser=SerialFake(b'')
            with self.assertRaises(ValueError):tool.collect(ser,timeout)
            self.assertEqual(ser.sent,[])

if __name__=='__main__':unittest.main()
