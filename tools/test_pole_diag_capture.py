from test_state_frame import INVALID as NEW_STATE
import unittest
from pole_diag_capture import Capture

BEFORE='100 100 0 33 33 16000 20000 40 0 0 1 1 1 1 0 123 0'
AFTER='101 100 1 0 33 0 20000 40 1 0 1 0 1 0 10 123 0'
def lines():
 return ['POLED2 BEGIN 4 8 1 1 1 0','POLED2 BEFORE '+BEFORE,'POLED2 AFTER '+AFTER,'POLED2 FAIL 3 1 101 0 1 2 3 4 5','POLED2 END 4 8']
class CaptureTest(unittest.TestCase):
 def test_complete_and_raw(self):
  c=Capture();r=None
  for line in lines():r=c.feed(line)
  self.assertEqual(r['run_id'],4);self.assertEqual(r['after']['failure_seq'],1)
  self.assertEqual(r['failure']['bytes'],[0,1,2,3,4,5]);self.assertEqual(r['raw_lines'],lines())
 def test_ninth_failed_read_retained_until_tenth_failure(self):
  # Device keeps the same successful sample/time through failures 1..9.
  before='104500 100000 4500 33 33 16000 20000 40 9 0 1 0 1 1 0 123 0'
  after='105000 100000 5000 33 33 16000 20000 40 10 0 1 0 0 0 4 123 0'
  frames=['POLED2 BEGIN 4 8 1 1 1 0','POLED2 BEFORE '+before,
          'POLED2 AFTER '+after,'POLED2 FAIL 3 10 105000 0 1 2 3 4 5','POLED2 END 4 8']
  c=Capture()
  for line in frames:r=c.feed(line)
  self.assertEqual(r['before']['last_attempt_ok'],0)
  self.assertEqual(r['before']['velocity_valid'],1)
  self.assertEqual(r['after']['ok'],0)
  self.assertEqual(r['failure']['sequence'],10)
  self.assertEqual(r['before']['sampled_us'],r['after']['sampled_us'])
  # Removing the last-read gate must not relax boolean validation.
  c=Capture();c.feed(frames[0]);bad=before.split();bad[11]='2'
  with self.assertRaises(ValueError):c.feed('POLED2 BEFORE '+' '.join(bad))
 def test_no_event(self):
  c=Capture();c.feed('POLED2 BEGIN 0 0 0 0 0 7');r=c.feed('POLED2 END 0 0')
  self.assertFalse(r['captured']);self.assertIsNone(r['before'])
 def test_transition_without_new_failure(self):
  c=Capture();c.feed('POLED2 BEGIN 4 8 1 0 1 0')
  c.feed('POLED2 BEFORE '+BEFORE)
  c.feed('POLED2 AFTER '+AFTER.replace('40 1 0','40 0 0'))
  r=c.feed('POLED2 END 4 8');self.assertIsNone(r['failure'])
 def test_strict_spaces(self):
  for s in [' '+lines()[0],lines()[0]+' ',lines()[0].replace(' ', '  ',1),lines()[0]+'\r',lines()[0].replace(' ','\t',1)]:
   with self.subTest(s=s),self.assertRaises(ValueError):Capture().feed(s)
 def test_snapshot_monotonic(self):
  for i,value in [(0,'99'),(1,'99'),(7,'39')]:
   c=Capture();c.feed(lines()[0]);c.feed(lines()[1]);f=AFTER.split();f[i]=value
   with self.assertRaises(ValueError):c.feed('POLED2 AFTER '+' '.join(f))
 def test_failure_identity(self):
  for s in ['POLED2 FAIL 3 0 101 0 1 2 3 4 5','POLED2 FAIL 3 2 101 0 1 2 3 4 5','POLED2 FAIL 3 1 99 0 1 2 3 4 5','POLED2 FAIL 3 1 102 0 1 2 3 4 5']:
   c=Capture()
   for line in lines()[:3]:c.feed(line)
   with self.assertRaises(ValueError):c.feed(s)
 def test_generation_identity(self):
  c=Capture()
  for s in lines()[:-1]:c.feed(s)
  with self.assertRaises(ValueError):c.feed('POLED2 END 4 9')
 def test_strict_frames(self):
  bad=['POLED2 BEGIN 4 2 0 0','POLED2 BEGIN -1 0 0 0','POLED2 BEGIN 4294967296 0 0 0','POLED2 BEGIN 0 0 0 0 extra','ERR POLEDIAG_BUSY','POLED2 END 0 0','garbage']
  for s in bad:
   with self.subTest(s=s),self.assertRaises(ValueError):Capture().feed(s)
 def test_duplicate_order_and_identity(self):
  for bad in ['POLED2 BEGIN 4 8 1 1 1 0','POLED2 AFTER '+AFTER,'POLED2 END 4 8']:
   c=Capture();c.feed(lines()[0])
   with self.assertRaises(ValueError):c.feed(bad)
  c=Capture()
  for s in lines()[:-1]:c.feed(s)
  with self.assertRaises(ValueError):c.feed('POLED2 END 5 8')
 def test_bounds(self):
  for index,value in [(3,'34'),(4,'32'),(10,'2'),(14,'256'),(15,'2097152'),(16,'8'),(7,str(2**64))]:
   fields=BEFORE.split();fields[index]=value;c=Capture();c.feed(lines()[0])
   with self.subTest(index=index),self.assertRaises(ValueError):c.feed('POLED2 BEFORE '+' '.join(fields))
 def test_long_background_and_error_rejected(self):
  for line in ['STATE '+'1'*2050+' 2 3 4','ERR '+'x'*2050]:
   with self.assertRaisesRegex(ValueError,'过长'):Capture().feed(line)
 def test_before_must_be_consistently_valid(self):
  for index,value in [(10,'0'),(12,'0'),(3,'32'),(2,'20001'),(5,'32001')]:
   fields=BEFORE.split();fields[index]=value;c=Capture();c.feed(lines()[0])
   with self.subTest(index=index),self.assertRaises(ValueError):c.feed('POLED2 BEFORE '+' '.join(fields))
 def test_background(self):
  c=Capture();self.assertIsNone(c.feed(NEW_STATE));self.assertIsNone(c.feed(NEW_STATE))
 def test_truncated_and_failure_byte(self):
  c=Capture()
  for s in lines()[:3]:c.feed(s)
  with self.assertRaises(ValueError):c.feed('POLED2 FAIL 3 1 101 0 1 2 3 4 256')

class CollectTest(unittest.TestCase):
 def test_only_read_query_and_complete(self):
  from pole_diag_capture import collect
  class Serial:
   def __init__(self):self.writes=[];self.data=('\n'.join(lines())+'\n').encode()
   def read_until(self,*a,**k):return b'residual\n'
   def write(self,b):self.writes.append(b);return len(b)
   @property
   def in_waiting(self):return len(self.data)
   def read(self,n):b=self.data[:n];self.data=self.data[n:];return b
  ser=Serial();r=collect(ser)
  self.assertEqual(ser.writes,[b'POLEDIAG?\n']);self.assertTrue(r['captured'])
 def test_crlf_accepts_one_cr_only(self):
  from pole_diag_capture import collect
  class Serial:
   def __init__(self,ending):self.data=(ending.join(lines())+ending).encode()
   def read_until(self,*a,**k):return b'\n'
   def write(self,b):return len(b)
   @property
   def in_waiting(self):return len(self.data)
   def read(self,n):b=self.data[:n];self.data=self.data[n:];return b
  self.assertTrue(collect(Serial('\r\n'))['captured'])
  with self.assertRaises(ValueError):collect(Serial('\r\r\n'))
 def test_short_write(self):
  from pole_diag_capture import collect
  class Serial:
   def read_until(self,*a,**k):return b'\n'
   def write(self,b):return len(b)-1
  with self.assertRaises(ValueError):collect(Serial())
 def test_timeout_no_partial_record(self):
  from pole_diag_capture import collect
  class Serial:
   def read_until(self,*a,**k):return b'\n'
   def write(self,b):return len(b)
   in_waiting=0
   def read(self,n):return b''
  ticks=iter([0,1,2,4])
  with self.assertRaises(TimeoutError):collect(Serial(),clock=lambda:next(ticks))

if __name__=='__main__':unittest.main()
