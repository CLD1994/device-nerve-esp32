"""串口联调工具单元测试；串口与时间均使用替身，不连接设备。"""
import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cartpole_host as host


class RigStateTest(unittest.TestCase):
    def make_rig(self):
        with patch.object(host.serial, "Serial") as serial_class, \
                patch.object(host.time, "time", side_effect=[0.0, 1.0]):
            return host.Rig("unused")

    def test_no_initial_state(self):
        rig = self.make_rig()
        self.assertIsNone(rig.last_state)

    def test_invalid_state_does_not_create_sample(self):
        rig = self.make_rig()
        with contextlib.redirect_stdout(io.StringIO()):
            rig._dispatch("STATE invalid 0 0 0")
        self.assertIsNone(rig.last_state)
        self.assertEqual(rig.state_count, 0)
        self.assertEqual(rig.unknown_count, 1)

    def test_valid_state_sets_latest_sample(self):
        rig = self.make_rig()
        rig._dispatch("STATE 80 -3141593 0 0")
        self.assertEqual(rig.last_state, ["80", "-3141593", "0", "0"])
        self.assertEqual(rig.state_count, 1)

    def test_state_without_frames_returns_failure(self):
        rig = self.make_rig()
        with patch.object(rig, "pump"), \
                patch.object(host.time, "time", side_effect=[0.0, 0.0, 1.0, 1.0]), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result = host.cmd_state(rig, SimpleNamespace(secs=1.0))
        self.assertEqual(result, 1)
        self.assertEqual(rig.state_count, 0)
        self.assertNotIn("x_um", output.getvalue())
        rig.ser.write.assert_not_called()


class CalibrationCommandTest(unittest.TestCase):
    def rig(self, response):
        rig = SimpleNamespace(last_reply=("OK", "CONFIRM_LEFT", -1), replies={})
        rig.sent = []
        rig.send_line = rig.sent.append
        rig.pump = lambda duration: setattr(rig, "last_reply", response)
        return rig

    def test_confirm_requires_matching_ack(self):
        for response, expected in [(None, 1), (("OK", "OTHER", 0), 1),
                                   (("ERR", "CONFIRM_LEFT", None), 1),
                                   (("OK", "CONFIRM_LEFT", -250000), 0)]:
            with self.subTest(response=response):
                rig = self.rig(response)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(host.cmd_confirm_left(rig, None), expected)
                self.assertEqual(rig.sent, ["CONFIRM LEFT"])

    def test_status_requires_terminal_response(self):
        rig = self.rig(("OK", "CAL_STORAGE", 0))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(host.cmd_calib_status(rig, None), 1)
        rig.pump = lambda duration: rig.replies.update(
            CAL_STATE=3, CAL_LENGTH_UM=500000, CAL_SAVED=1, CAL_STORAGE=0)
        self.assertEqual(host.cmd_calib_status(rig, None), 0)
        self.assertEqual(rig.sent, ["CALIB?", "CALIB?"])
        rig.pump = lambda duration: None
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(host.cmd_calib_status(rig, None), 1)


if __name__ == "__main__":
    unittest.main()
