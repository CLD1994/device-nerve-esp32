import unittest
from step50k_plan import calculate

class BudgetTests(unittest.TestCase):
    def test_fixed_target(self):
        b=calculate()
        self.assertEqual(b['target_step_hz'],50000)
        self.assertAlmostEqual(b['ramp_s'],1250/9000)
        self.assertAlmostEqual(b['ramp_mm'],86.8055555556)
        self.assertIsNone(b['normal_total_mm'])
        self.assertIsNone(b['watchdog_stop_mm'])
        self.assertFalse(b['motion_authorized'])

    def test_normal_and_watchdog_are_independent(self):
        b=calculate(hold_s=.1, normal_decel=9000, watchdog_decel=5000,
                    watchdog_ms=100)
        self.assertAlmostEqual(b['normal_total_mm'],298.611111111)
        self.assertAlmostEqual(b['watchdog_stop_mm'],281.25)
        self.assertIsNone(b['fault_budget_mm'])
        self.assertFalse(b['physical_stop_bound_verified'])

    def test_inflight_is_additional_delay_not_hidden(self):
        b=calculate(watchdog_decel=5000, watchdog_ms=100,
                    inflight_ms=20, margin_mm=50, window_s=.3,
                    start_from_left_mm=100)
        self.assertAlmostEqual(b['fault_budget_mm'],731.25)
        self.assertAlmostEqual(b['forward_clearance_mm'],743.325)
        self.assertTrue(b['conditional_fault_budget_fits'])
        self.assertFalse(b['motion_authorized'])

    def test_unknown_inputs_do_not_become_zero(self):
        b=calculate(watchdog_decel=5000, watchdog_ms=100, margin_mm=50, window_s=.3)
        self.assertIsNone(b['fault_budget_mm'])
        self.assertIsNone(b['conditional_fault_budget_fits'])

    def test_reject_invalid_inputs(self):
        for params in ({'hold_s':-1},{'normal_decel':0},{'watchdog_ms':0},
                       {'inflight_ms':float('nan')},{'margin_mm':float('inf')},
                       {'start_from_left_mm':900},{'window_s':.01}):
            with self.subTest(params=params), self.assertRaises(ValueError): calculate(**params)

    def test_insufficient_distance_is_not_pass(self):
        b=calculate(watchdog_decel=5000,watchdog_ms=100,inflight_ms=20,
                    margin_mm=50,window_s=.4,start_from_left_mm=100)
        self.assertFalse(b['conditional_fault_budget_fits'])

    def test_run_is_not_an_available_command(self):
        import contextlib, io
        from step50k_plan import main
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(['run'])
        self.assertEqual(error.exception.code,2)

    def test_normal_braking_can_need_more_room_than_watchdog(self):
        b=calculate(hold_s=.1,normal_decel=100,watchdog_decel=5000,
                    watchdog_ms=100,inflight_ms=20,margin_mm=50,
                    window_s=.3,start_from_left_mm=100)
        self.assertFalse(b['conditional_normal_budget_fits'])
        self.assertTrue(b['conditional_fault_budget_fits'])
        self.assertFalse(b['motion_authorized'])

    def test_overflowing_budget_is_rejected(self):
        with self.assertRaises(ValueError): calculate(hold_s=1e308,normal_decel=9000)

    def test_offline_cli_keeps_unknown_and_never_authorizes(self):
        import contextlib, io, json
        from step50k_plan import main
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['plan']),0)
        result=json.loads(output.getvalue())
        self.assertIsNone(result['inputs']['hold_s'])
        self.assertFalse(result['motion_authorized'])
