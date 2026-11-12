# -*- coding: utf-8 -*-
"""max_accel_run 纯逻辑单元测试（标准库 unittest，不触碰串口与真实文件）。

被测对象是 tools/max_accel_run.py 中具有独立行为契约的纯函数：
单段判定（FAULT 优先、100/300 µm 三分）、组合全部通过规则、
加速到达判据、停稳判据、超时预算与巡航保持时间表。段执行与命令入口
使用受 TestRig 接口约束的替身验证主机副作用契约，不连接设备。
"""

import unittest
from collections import deque

import max_accel_run as m


class ClassifyOffsetTest(unittest.TestCase):
    def test_fault_takes_priority(self):
        self.assertEqual(m.classify_offset(0, faulted=True), "FAIL")
        self.assertEqual(m.classify_offset(-5000, faulted=True), "FAIL")

    def test_pass_band(self):
        self.assertEqual(m.classify_offset(0, False), "PASS")
        self.assertEqual(m.classify_offset(100, False), "PASS")      # 边界含
        self.assertEqual(m.classify_offset(-100, False), "PASS")

    def test_margin_band(self):
        self.assertEqual(m.classify_offset(101, False), "MARGIN")
        self.assertEqual(m.classify_offset(299, False), "MARGIN")
        self.assertEqual(m.classify_offset(-300 + 1, False), "MARGIN")

    def test_fail_band(self):
        # 方案语义「净偏移 > 300 µm 判失败」：300 本身落在复测带
        self.assertEqual(m.classify_offset(300, False), "MARGIN")
        self.assertEqual(m.classify_offset(301, False), "FAIL")
        self.assertEqual(m.classify_offset(-301, False), "FAIL")


class CombineVerdictsTest(unittest.TestCase):
    def test_any_failure_rejects_combination(self):
        ok, label = m.combine_verdicts(["PASS", "PASS", "FAIL"])
        self.assertFalse(ok)

    def test_majority_fail(self):
        ok, _ = m.combine_verdicts(["FAIL", "FAIL", "PASS"])
        self.assertFalse(ok)

    def test_majority_margin_is_not_ok(self):
        ok, _ = m.combine_verdicts(["MARGIN", "MARGIN", "PASS"])
        self.assertFalse(ok)

    def test_all_three_distinct_is_conservative_fail(self):
        ok, label = m.combine_verdicts(["PASS", "MARGIN", "FAIL"])
        self.assertFalse(ok)
        self.assertTrue(label)

    def test_single_sample(self):
        self.assertTrue(m.combine_verdicts(["PASS"])[0])
        self.assertFalse(m.combine_verdicts(["MARGIN"])[0])
        self.assertFalse(m.combine_verdicts(["FAIL"])[0])


class ReachedTest(unittest.TestCase):
    def test_within_noise_tolerance(self):
        # tol = max(2σ=10, 5%×50=2.5) = 10
        self.assertTrue(m.reached(44, 50))
        self.assertTrue(m.reached(58, 50))

    def test_outside_tolerance(self):
        self.assertFalse(m.reached(39, 50))
        self.assertFalse(m.reached(61, 50))

    def test_small_target_uses_noise_floor(self):
        # 噪声容差不能让反方向或零速算作到达。
        self.assertFalse(m.reached(-4, 5))
        self.assertFalse(m.reached(0, 5))


class SettledRunTest(unittest.TestCase):
    def test_needs_full_run(self):
        self.assertFalse(m.settled_run([0, 0, 0, 0, 0, 0, 0], run=8))

    def test_consecutive_low(self):
        self.assertTrue(m.settled_run([30, 10, 0, 0, 0, 0, 0, 0, 0], run=8))

    def test_last_sample_breaks_run(self):
        self.assertFalse(m.settled_run([0] * 7 + [11], run=8))

    def test_deque_input(self):
        d = deque([0] * 8, maxlen=8)
        self.assertTrue(m.settled_run(d))


class LegTimesTest(unittest.TestCase):
    def test_ramp_plus_margin(self):
        self.assertAlmostEqual(m.leg_times(550, 5000, 1.0)[0], 0.61)
        self.assertAlmostEqual(m.leg_times(550, 5000, 1.0)[1], 1.11)

    def test_high_acc_short_ramp(self):
        self.assertAlmostEqual(m.leg_times(50, 30000, 1.0)[0],
                               50 / 30000 + 0.5)


class HoldTimeTest(unittest.TestCase):
    def test_known_speeds_exact(self):
        self.assertEqual(m.hold_time(50), 1.20)
        self.assertEqual(m.hold_time(550), 0.16)

    def test_interpolated_between_known(self):
        # 200 介于 120(0.64) 与 300(0.27) 之间线性内插
        want = 0.64 + (0.27 - 0.64) * (200 - 120) / (300 - 120)
        self.assertAlmostEqual(m.hold_time(200), want)

    def test_clamps_outside_table(self):
        self.assertEqual(m.hold_time(30), 1.20)
        self.assertEqual(m.hold_time(600), 0.16)


# 协议边界替身：不打开串口、不等待真实时间、不写真实文件。
from unittest.mock import patch, create_autospec, mock_open
from types import SimpleNamespace


class MotionSafetyTest(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.rig = create_autospec(m.TestRig, instance=True)
        self.rig.samples = deque([(self.now, 0, 0, 0, 0)])
        self.rig.fault_events = []
        self.rig.last_mode = ("READY", "NONE")
        self.rig.last_reply = None
        self.rig.last_state_tuple.side_effect = lambda: (
            (self.rig.samples[-1][1], self.rig.samples[-1][3]) if self.rig.samples else None)
        self.rig.now.side_effect = lambda: self.now - 10
        self.clock = patch.object(m.time, "monotonic", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.sent = []
        self.rig.send_line.side_effect = self.sent.append
        self.rig.pump.side_effect = self.pump
        self.velocity = None
        self.emit = True
        self.pumps = 0

    def pump(self, duration):
        self.pumps += 1
        if self.pumps > 200:
            self.fail("会话未在有界时间内终止")
        self.now += duration
        if self.emit:
            commanded = int(self.sent[-1].split()[1]) if self.sent and self.sent[-1].startswith("VEL ") else 0
            vx = commanded if self.velocity is None else self.velocity
            self.rig.samples.append((self.now, 0, 0, vx, 0))

    def test_negative_leg_reaches_negative_velocity(self):
        result = m.run_leg(self.rig, -300, .1, 5000)
        self.assertTrue(result[3])
        self.assertEqual(result[4], "")

    def test_missing_state_aborts_without_nonzero_command(self):
        self.rig.samples.clear()
        self.emit = False
        with self.assertRaises(m.ExperimentAborted):
            m.run_leg(self.rig, 50, .1, 5000)
        self.assertFalse(any(x != "VEL 0" for x in self.sent))

    def test_stale_state_aborts_without_nonzero_command(self):
        self.now += 1
        with self.assertRaises(m.ExperimentAborted):
            m.run_leg(self.rig, 50, .1, 5000)
        self.assertFalse(any(x != "VEL 0" for x in self.sent))

    def test_reach_timeout_requests_stop_and_aborts(self):
        self.velocity = 0
        with self.assertRaises(m.ExperimentAborted):
            m.run_leg(self.rig, 50, 10, 5000)
        self.assertEqual(self.sent[-1], "VEL 0")
        self.assertLess(self.now, 11)

    def test_fault_does_not_reset_or_enable(self):
        def fail_on_pump(duration):
            self.pump(duration)
            self.rig.last_mode = ("FAULT", "STEP_LOSS")
            self.rig.fault_events.append((self.now, "STEP_LOSS"))
        self.rig.pump.side_effect = fail_on_pump
        result = m.run_segment(self.rig, 50, 5000)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(result["aborted"])
        self.assertNotIn("RESET", self.sent)
        self.assertNotIn("ENABLE", self.sent)
        self.assertEqual(self.sent[-1], "VEL 0")

    def test_segment_does_not_reverse_after_unsettled_leg(self):
        with patch.object(m, "run_leg", return_value=(0, 0, False, False, "settle-timeout")) as leg:
            result = m.run_segment(self.rig, 50, 5000)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(leg.call_count, 1)

    def test_calibration_uses_length_reply_and_stays_disabled(self):
        self.rig.query.return_value = ("DISABLED", "NONE")
        self.rig.last_mode = ("DISABLED", "NONE")
        def replies(duration):
            self.rig.last_reply = ("OK", "MARK_LEFT", 20000) if self.sent[-1] == "MARK LEFT" else ("OK", "MARK_RIGHT", 400000)
        self.rig.pump.side_effect = replies
        with patch("builtins.input", return_value=""), patch("builtins.print") as output:
            self.assertEqual(m.cmd_calib(self.rig, SimpleNamespace()), 0)
        self.assertNotIn("ENABLE", self.sent)
        self.assertTrue(any("400000" in str(c) for c in output.call_args_list))


class ConservativeVerdictTest(unittest.TestCase):
    def test_missing_offset_is_failure(self):
        self.assertEqual(m.classify_offset(None, False), "FAIL")

    def test_mixed_results_are_not_feasible(self):
        self.assertFalse(m.combine_verdicts(["PASS", "PASS", "FAIL"])[0])

    def test_negative_velocity_has_symmetric_tolerance(self):
        self.assertTrue(m.reached(-475, -500))
        self.assertFalse(m.reached(500, -500))

    def test_negative_leg_has_symmetric_budget(self):
        self.assertEqual(m.leg_times(-550, 5000, 0), m.leg_times(550, 5000, 0))

    def test_empty_results_are_not_feasible(self):
        self.assertFalse(m.combine_verdicts([])[0])


class FurtherMotionSafetyTest(MotionSafetyTest):
    def test_unknown_mode_does_not_start(self):
        self.rig.last_mode = None
        with self.assertRaises(m.ExperimentAborted):
            m.run_leg(self.rig, 50, .1, 5000)
        self.assertEqual(self.sent, ["VEL 0"])

    def test_not_at_rest_does_not_start(self):
        self.rig.samples[-1] = (self.now, 0, 0, 100, 0)
        with self.assertRaises(m.ExperimentAborted):
            m.run_leg(self.rig, 50, .1, 5000)
        self.assertEqual(self.sent, ["VEL 0"])

    def test_settle_timeout_does_not_pass(self):
        self.velocity = 50
        with self.assertRaisesRegex(m.ExperimentAborted, "settle-timeout"):
            m.run_leg(self.rig, 50, .1, 5000)
        self.assertEqual(self.sent[-1], "VEL 0")

    def test_serial_exception_requests_stop(self):
        self.rig.pump.side_effect = OSError("disconnected")
        with self.assertRaises(OSError):
            m.run_leg(self.rig, 50, .1, 5000)
        self.assertEqual(self.sent[-1], "VEL 0")

    def test_keyboard_interrupt_requests_stop(self):
        self.rig.pump.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            m.run_leg(self.rig, 50, .1, 5000)
        self.assertEqual(self.sent[-1], "VEL 0")

    def test_cached_ready_is_not_accepted(self):
        self.rig.query.side_effect = lambda: self.rig.last_mode
        self.assertFalse(m.ensure_ready(self.rig))

    def test_config_does_not_accept_previous_ack(self):
        self.rig.last_reply = ("OK", "ACC_MAX", 5000)
        self.assertFalse(m.set_config(self.rig, "ACC_MAX", 5000))

    def test_calibration_rejects_wrong_reply_name(self):
        self.rig.query.return_value = ("DISABLED", "NONE")
        self.rig.pump.side_effect = lambda _: setattr(self.rig, "last_reply", ("OK", "ACC_MAX", 5000))
        with patch("builtins.input", return_value=""):
            self.assertEqual(m.cmd_calib(self.rig, SimpleNamespace()), 1)
        self.assertEqual(self.sent, ["MARK LEFT"])

    def test_final_stop_send_failure_prevents_reverse_and_pass(self):
        with patch.object(m, "request_stop", return_value=False):
            result = m.run_segment(self.rig, 50, 5000)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(result["aborted"])
        self.assertNotIn("VEL -50", self.sent)

    def test_stop_request_reports_write_failure(self):
        self.rig.send_line.side_effect = OSError("closed")
        self.assertFalse(m.request_stop(self.rig))

    def test_center_brakes_inside_band_before_declaring_success(self):
        self.rig.samples[-1] = (self.now, 1000, 0, 100, 0)
        self.assertTrue(m.move_to_center(self.rig))
        self.assertEqual(self.sent[0], "VEL 0")
        self.assertTrue(all(c == "VEL 0" for c in self.sent))

    def test_matrix_io_exception_is_recorded_as_aborted(self):
        args = SimpleNamespace(speeds=[50], accs=[5000], reps=3, outdir="unused")
        with patch.object(m, "ensure_ready", return_value=True), patch.object(m, "move_to_center", side_effect=OSError("lost")), patch.object(m, "write_segments_csv"), patch.object(m, "write_summary") as summary:
            with self.assertRaises(OSError):
                m.cmd_matrix(self.rig, args)
        self.assertTrue(summary.call_args.args[-1])
        self.assertEqual(self.sent[-1], "VEL 0")

    def test_step_response_initial_motion_never_starts_next_step(self):
        self.velocity = 100
        self.rig._t0 = 10
        with patch.object(m, "ensure_ready", return_value=True), patch.object(m, "set_config", return_value=True), patch("builtins.open", mock_open()):
            with self.assertRaisesRegex(m.ExperimentAborted, "settle-timeout"):
                m.cmd_step_response(self.rig, SimpleNamespace(outdir="unused", step_v=50))
        self.assertTrue(all(c == "VEL 0" for c in self.sent))

    def test_matrix_aborts_on_first_incomplete_segment(self):
        row = dict(v_mm_s=50, acc_mm_s2=5000, verdict="FAIL", offset_um=None,
                   faulted=False, aborted=True, notes="missing-state")
        args = SimpleNamespace(speeds=[50, 120], accs=[5000, 10000], reps=3, outdir="unused")
        with patch.object(m, "ensure_ready", return_value=True), patch.object(m, "move_to_center", return_value=True), patch.object(m, "set_config", return_value=True), patch.object(m, "run_segment", return_value=row) as run, patch.object(m, "write_segments_csv"), patch.object(m, "write_summary"):
            self.assertEqual(m.cmd_matrix(self.rig, args), 1)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(self.sent, ["VEL 0"])

    def test_step_response_records_all_received_frames(self):
        self.rig._t0 = 10
        def burst(duration):
            self.now += duration
            for n in range(3):
                self.rig.samples.append((self.now + n / 10000, n, 0, int(self.sent[-1].split()[1]), 0))
        self.rig.pump.side_effect = burst
        sink = mock_open()
        with patch.object(m, "ensure_ready", return_value=True), patch.object(m, "set_config", return_value=True), patch("builtins.open", sink):
            self.assertEqual(m.cmd_step_response(self.rig, SimpleNamespace(outdir="unused", step_v=50)), 0)
        writes = [c.args[0] for c in sink().write.call_args_list]
        self.assertEqual(len(writes) - 1, len(self.rig.samples) - 1)
        self.assertEqual(self.sent[-1], "VEL 0")

    def test_partial_summary_does_not_report_feasible(self):
        rows = [dict(v_mm_s=50, acc_mm_s2=5000, verdict="PASS")]
        sink = mock_open()
        with patch("builtins.open", sink):
            m.write_summary("unused", rows, SimpleNamespace(speeds=[50], accs=[5000], reps=3), True)
        text = "".join(c.args[0] for c in sink().write.call_args_list)
        self.assertNotIn("≥", text)


class CommandExitTest(unittest.TestCase):
    def test_failed_final_stop_makes_success_nonzero_and_closes_port(self):
        with patch.object(m.sys, "argv", ["tool", "--port", "unused", "smoke"]), patch.object(m, "TestRig") as rig, patch.object(m.os, "makedirs"), patch.object(m, "cmd_smoke", return_value=0), patch.object(m, "request_stop", return_value=False):
            with self.assertRaises(SystemExit) as exit:
                m.main()
        self.assertEqual(exit.exception.code, 1)
        rig.return_value.close.assert_called_once()

    def test_calibration_does_not_send_final_velocity_command(self):
        with patch.object(m.sys, "argv", ["tool", "--port", "unused", "calib"]), patch.object(m, "TestRig") as rig, patch.object(m.os, "makedirs"), patch.object(m, "cmd_calib", return_value=0), patch.object(m, "request_stop") as stop:
            with self.assertRaises(SystemExit) as exit:
                m.main()
        self.assertEqual(exit.exception.code, 0)
        stop.assert_not_called()
        rig.return_value.close.assert_called_once()


class ArgumentSafetyTest(unittest.TestCase):
    def test_invalid_motion_inputs_fail_before_opening_port(self):
        cases = [("matrix", "--reps", "0"), ("matrix", "--speeds", "0"),
                 ("matrix", "--accs", "-1"), ("step-response", "--step-v", "-5"),
                 ("matrix", "--accs", "10000", "5000")]
        for case in cases:
            with self.subTest(case=case), patch.object(m.sys, "argv", ["tool", "--port", "unused", *case]), patch.object(m, "TestRig") as rig, patch.object(m.os, "makedirs"), patch.object(m, "cmd_matrix", return_value=0), patch.object(m, "cmd_step_response", return_value=0):
                with self.assertRaises(SystemExit) as exit:
                    m.main()
                self.assertEqual(exit.exception.code, 2)
                rig.assert_not_called()

if __name__ == "__main__":
    unittest.main()
