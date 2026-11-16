import unittest
from pole_diag_capture import Capture

BEFORE='100 100 0 33 33 16000 20000 40 0 0 1 1 1 1 0 123 0'
AFTER='101 100 1 0 33 0 20000 40 1 0 1 0 1 0 10 123 0'
def lines():
 return ['POLED1 BEGIN 4 1 1 0','POLED1 BEFORE '+BEFORE,'POLED1 AFTER '+AFTER,'POLED1 FAIL 3 1 101 0 1 2 3 4 5','POLED1 END 4']
class CaptureTest(unittest.TestCase):
 def test_complete_and_raw(self):
  c=Capture();r=None
  for line in lines():r=c.feed(line)
  self.assertEqual(r['run_id'],4);self.assertEqual(r['after']['failure_seq'],1)
  self.assertEqual(r['failure']['bytes'],[0,1,2,3,4,5]);self.assertEqual(r['raw_lines'],lines())
 def test_no_event(self):
  c=Capture();c.feed('POLED1 BEGIN 0 0 0 7');r=c.feed('POLED1 END 0')
  self.assertFalse(r['captured']);self.assertIsNone(r['before'])
 def test_strict_frames(self):
  bad=['POLED1 BEGIN 4 2 0 0','POLED1 BEGIN -1 0 0 0','POLED1 BEGIN 4294967296 0 0 0','POLED1 BEGIN 0 0 0 0 extra','ERR POLEDIAG_BUSY','POLED1 END 0','garbage']
  for s in bad:
   with self.subTest(s=s),self.assertRaises(ValueError):Capture().feed(s)
 def test_duplicate_order_and_identity(self):
  for bad in ['POLED1 BEGIN 4 1 1 0','POLED1 AFTER '+AFTER,'POLED1 END 4']:
   c=Capture();c.feed(lines()[0])
   with self.assertRaises(ValueError):c.feed(bad)
  c=Capture()
  for s in lines()[:-1]:c.feed(s)
  with self.assertRaises(ValueError):c.feed('POLED1 END 5')
 def test_bounds(self):
  for index,value in [(3,'34'),(4,'32'),(10,'2'),(14,'256'),(15,'2097152'),(16,'8'),(7,str(2**64))]:
   fields=BEFORE.split();fields[index]=value;c=Capture();c.feed(lines()[0])
   with self.subTest(index=index),self.assertRaises(ValueError):c.feed('POLED1 BEFORE '+' '.join(fields))
 def test_long_background_and_error_rejected(self):
  for line in ['STATE '+'1'*2050+' 2 3 4','ERR '+'x'*2050]:
   with self.assertRaisesRegex(ValueError,'过长'):Capture().feed(line)
 def test_before_must_be_consistently_valid(self):
  for index,value in [(10,'0'),(11,'0'),(12,'0'),(3,'32'),(2,'20001'),(5,'32001')]:
   fields=BEFORE.split();fields[index]=value;c=Capture();c.feed(lines()[0])
   with self.subTest(index=index),self.assertRaises(ValueError):c.feed('POLED1 BEFORE '+' '.join(fields))
 def test_background(self):
  c=Capture();self.assertIsNone(c.feed('VEL_VALID 1 0'));self.assertIsNone(c.feed('STATE 1 2 3 4'))
 def test_truncated_and_failure_byte(self):
  c=Capture()
  for s in lines()[:3]:c.feed(s)
  with self.assertRaises(ValueError):c.feed('POLED1 FAIL 3 1 101 0 1 2 3 4 256')

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
