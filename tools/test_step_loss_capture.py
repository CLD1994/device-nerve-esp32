import unittest
from step_loss_capture import Capture, FIELDS, collect
from unittest.mock import patch

class CaptureTests(unittest.TestCase):
    def complete(self, capture, event=1):
        for name in sorted(FIELDS):
            self.assertIsNone(capture.feed(f"SL1 {event} {name} {1 if name=='VERSION' else -10}"))
        return capture.feed(f"SL1 {event} END 1")
    def test_complete_and_background(self):
        c=Capture()
        self.assertIsNone(c.feed("STATE 1 -2 3 4"))
        self.assertIsNone(c.feed("VEL_VALID 0 1"))
        result=self.complete(c)
        self.assertEqual(result['event_id'],1)
        self.assertEqual(result['E_COMPARED_UM'],-10)
    def test_partial_rejected(self):
        with self.assertRaises(ValueError): Capture().feed("SL1 1 END 1")
    def test_mixed_event_rejected(self):
        c=Capture(); c.feed("SL1 1 VERSION 1")
        with self.assertRaises(ValueError): c.feed("SL1 2 C_UM 10")
    def test_duplicate_rejected(self):
        c=Capture(); c.feed("SL1 1 VERSION 1")
        with self.assertRaises(ValueError): c.feed("SL1 1 VERSION 1")
    def test_error_and_noise(self):
        for line in ["ERR STEPLOSS_DISABLED","ERR STEPLOSS_BUSY","ERR STEPLOSS_NONE","STATE broken","SL1 1 UNKNOWN 1"]:
            with self.subTest(line=line), self.assertRaises(ValueError): Capture().feed(line)
    def test_wrong_version(self):
        c=Capture()
        for name in FIELDS: c.feed(f"SL1 1 {name} 2")
        with self.assertRaises(ValueError): c.feed("SL1 1 END 1")

class SerialFake:
    def __init__(self, chunks): self.chunks=list(chunks); self.writes=[]
    def read_until(self, end): return b"partial boundary\n"
    def write(self, value): self.writes.append(value); return len(value)
    def flush(self): pass
    @property
    def in_waiting(self): return len(self.chunks[0]) if self.chunks else 0
    def read(self, n): return self.chunks.pop(0) if self.chunks else b""

class CollectTests(unittest.TestCase):
    def test_only_readonly_command_and_fragmented_reply(self):
        wire="STATE 0 0 0 0\n"+"".join(
            f"SL1 4 {name} {1 if name=='VERSION' else 0}\n" for name in sorted(FIELDS)
        )+"SL1 4 END 1\n"
        data=wire.encode("ascii")
        ser=SerialFake([data[i:i+7] for i in range(0,len(data),7)])
        result=collect(ser)
        self.assertEqual(result['event_id'],4)
        self.assertEqual(ser.writes,[b"STEPLOSS?\n"])
    def test_short_write_rejected_without_flush(self):
        ser=SerialFake([])
        with patch.object(ser,"write",return_value=3), patch.object(ser,"flush") as flush:
            with self.assertRaises(ValueError): collect(ser)
            flush.assert_not_called()
    def test_partial_does_not_succeed(self):
        ser=SerialFake([b"SL1 4 VERSION 1\n"])
        with patch("step_loss_capture.time.monotonic",side_effect=[0,1,4]):
            with self.assertRaises(TimeoutError): collect(ser)
        self.assertEqual(ser.writes,[b"STEPLOSS?\n"])

if __name__=='__main__': unittest.main()
