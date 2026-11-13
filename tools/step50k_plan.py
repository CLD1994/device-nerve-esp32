#!/usr/bin/env python3
"""50 kHz / 1250 mm/s、可选100..30000 mm/s²离线计划器；没有串口、配置或运动入口。"""
import argparse
import json
import math

TARGET_SPEED_MM_S = 1250.0
TARGET_ACCEL_MM_S2 = 9000.0
STEPS_PER_MM = 40.0
TRAVEL_MM = 853.325
SOFT_MARGIN_MM = 10.0


def calculate(*, acceleration=9000, hold_s=None, normal_decel=None, watchdog_decel=None,
              watchdog_ms=None, inflight_ms=None, margin_mm=None,
              window_s=None, start_from_left_mm=None):
    """返回条件预算，不以用户输入的减速度或延迟假设证明物理停止上界。"""
    if isinstance(acceleration, bool) or not isinstance(acceleration, (int,float)) or not math.isfinite(acceleration) or acceleration != int(acceleration) or not 100 <= acceleration <= 30000:
        raise ValueError("acceleration必须是100..30000 mm/s²整数；软件范围不代表物理极限")
    inputs = dict(acceleration=acceleration, hold_s=hold_s, normal_decel=normal_decel,
                  watchdog_decel=watchdog_decel, watchdog_ms=watchdog_ms,
                  inflight_ms=inflight_ms, margin_mm=margin_mm,
                  window_s=window_s, start_from_left_mm=start_from_left_mm)
    for name, value in inputs.items():
        if value is not None:
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError(name + ' 必须为非负有限数')
            if name in ('normal_decel', 'watchdog_decel', 'watchdog_ms', 'window_s') and value == 0:
                raise ValueError(name + ' 必须大于零')
    v, a = TARGET_SPEED_MM_S, acceleration
    ramp_s = v / a
    ramp_mm = v * v / (2 * a)
    if window_s is not None and window_s < ramp_s + (hold_s or 0):
        raise ValueError('非零窗口不足以包含理想升速及已指定保持段')
    if start_from_left_mm is not None and not SOFT_MARGIN_MM <= start_from_left_mm <= TRAVEL_MM - SOFT_MARGIN_MM:
        raise ValueError('起点必须位于已标定行程的软件边界内')
    normal_mm = None
    if hold_s is not None and normal_decel is not None:
        normal_mm = ramp_mm + v * hold_s + v * v / (2 * normal_decel)
    watchdog_mm = None
    if watchdog_ms is not None and watchdog_decel is not None:
        watchdog_mm = v * watchdog_ms / 1000 + v * v / (2 * watchdog_decel)
    forward_mm = None if start_from_left_mm is None else TRAVEL_MM - SOFT_MARGIN_MM - start_from_left_mm
    fault_mm = None
    if all(value is not None for value in (watchdog_mm, inflight_ms, margin_mm, window_s)):
        # 在整个非零窗口按速度上限估计前进；不依赖实际加速度达到所选值。
        fault_mm = v * window_s + v * inflight_ms / 1000 + watchdog_mm + margin_mm
    normal_budget = None if normal_mm is None or margin_mm is None else normal_mm + margin_mm
    normal_fits = None if normal_budget is None or forward_mm is None else normal_budget <= forward_mm
    if any(value is not None and not math.isfinite(value)
           for value in (normal_mm, watchdog_mm, fault_mm, normal_budget)):
        raise ValueError("输入导致预算数值溢出")
    fits = None if fault_mm is None or forward_mm is None else fault_mm <= forward_mm
    return dict(target_speed_mm_s=v, target_accel_mm_s2=a,
                target_step_hz=v * STEPS_PER_MM, travel_mm=TRAVEL_MM,
                soft_margin_mm=SOFT_MARGIN_MM, ramp_s=ramp_s, ramp_mm=ramp_mm,
                inputs=inputs, normal_total_mm=normal_mm,
                watchdog_stop_mm=watchdog_mm, forward_clearance_mm=forward_mm,
                normal_budget_mm=normal_budget, conditional_normal_budget_fits=normal_fits,
                fault_budget_mm=fault_mm, conditional_fault_budget_fits=fits,
                physical_stop_bound_verified=False, motion_authorized=False,
                limitations=[
                    '仅离线条件计算，没有读取设备、验证配置或执行运动。',
                    '保持时间、减速度、命令在途延迟和附加余量未输入时保持未知，不默认为零。',
                    '普通VEL 0当前使用ACC_MAX；看门狗使用WDT_DEC，二者须分别核对。',
                    '在途延迟必须包含最后非零命令在主机、USB、串口及固件接收队列中的滞留；晚到命令可再次喂狗。',
                    '预算成立还依赖实际速度不超过目标上限、指定减速度持续可达及在途延迟确有上界；输入值不证明这些条件。',
                    '软限位越界后才钳制目标，不承担提前制动；断电或打滑时受控减速公式可能失效。',
                    '500Hz STATE接收时间和滤波速度不能独自证明所选实际加速度、50kHz实际波形、无失步或无打滑。',
                    '条件预算满足也不授权运动；本工具没有run入口。'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan'])
    parser.add_argument('--acceleration',type=int,default=9000,help='请求加速度mm/s²，100..30000；默认9000，软件上限非物理极限')
    for option, help_text in (
            ('hold-s', '高速保持时间，秒；未指定则未知'),
            ('normal-decel', '正常停止减速度假设，mm/s²'),
            ('watchdog-decel', '看门狗停止减速度假设，mm/s²'),
            ('watchdog-ms', '看门狗超时，毫秒；0代表关闭，不可用于本预算'),
            ('inflight-ms', '最后非零命令在途延迟上界假设，毫秒'),
            ('margin-mm', '额外距离余量，mm；不包含已计算的延迟和减速'),
            ('window-s', '从首次非零写入开始的绝对非零时窗，秒'),
            ('start-from-left-mm', '从左物理参考点到起点的距离，mm')):
        parser.add_argument('--' + option, type=float, help=help_text)
    args = vars(parser.parse_args(argv))
    args.pop('command')
    try:
        result = calculate(**args)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    # 退出0仅代表离线计算成功；不代表试验通过或允许运动。
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
