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


if __name__ == "__main__":
    unittest.main()
