#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
max_accel_run — 最大加速度实测执行器（方案：docs/max-accel-exploration-plan.md）

依赖：pip install pyserial；与 cartpole_host.py 同目录运行（复用 Rig 串口会话）。

子命令：
  calib          引导两点标定（人工推车到两端，各按回车确认）
  smoke          冒烟段：ACC_MAX 5000、50 mm/s 一次往返
  matrix         实验矩阵：4 速度点 × 6 加速度档 × 3 段往返（可参数化，首次异常即停止）
  step-response  VEL 阶跃响应记录（τ / 实际加速度测量，回填 sim2real-spec）

用法示例：
  python max_accel_run.py --port COM7 calib
  python max_accel_run.py --port COM7 matrix
  python max_accel_run.py --port COM7 matrix --speeds 50 --accs 5000 10000
  python max_accel_run.py --port COM7 step-response

产出（--out 目录，默认 results/maxaccel-<启动时间>/）：
  raw.log            全部串口行（带相对时间戳）
  segments.csv       每段：速度、加速度、段序、判定、净偏移、备注
  step-response.csv  阶跃记录：t、x_um、vx_mm_s
  summary.txt        可行域矩阵与组合判定

判定规则（方案「判定规则」节）：
  FAULT                                        → FAIL
  |往返净偏移| > 300 µm（12 步）                → FAIL
  |净偏移| ≤ 100 µm                            → PASS
  100–300 µm                                   → MARGIN
  不完整、超时、缺失/陈旧状态 → FAIL 并中止；不会自动 RESET/ENABLE。
  只有计划的全部段都 PASS，才报告该档完整通过主机检查。
  净偏移不能单独证明无丢步，也不能据此确定机械最大加速度。
"""

import argparse
import csv
import os
import sys
import time
from collections import deque

from cartpole_host import Rig

# ---- 方案固定值（docs/max-accel-exploration-plan.md） ----

SPEEDS_DEFAULT = [50, 120, 300, 550]          # mm/s
ACCS_DEFAULT = [5000, 10000, 15000, 20000, 25000, 30000]  # mm/s²
REPS_DEFAULT = 3                               # 每组合段数

OFFSET_PASS_UM = 100    # 净偏移 ≤ 此值判 PASS
OFFSET_FAIL_UM = 300    # 净偏移 > 此值判 FAIL（300 µm = 12 步 @25 µm/step）

FEED_PERIOD_S = 0.05    # 喂狗周期（WDT_MS 默认 100 ms）
VX_NOISE_SIGMA = 5      # 固件速度估计静止噪声指标 σ ≤ 5 mm/s
VX_SETTLED = 2 * VX_NOISE_SIGMA   # 停稳判据 |vx| ≤ 2σ（协议指标）
SETTLE_RUN = 8          # 连续拍数（@50 ms pump ≈ 0.4 s）

# 每速度点：单方向目标位移（mm）、按最不利档（最低加速度）的巡航保持时间（s）
LEG_PROFILE = {
    50:  (60,  1.20),
    120: (80,  0.64),
    300: (100, 0.27),
    550: (150, 0.16),
}


# ---- 纯逻辑（单元测试覆盖） ----

def classify_offset(offset_um, faulted):
    """单段判定：FAULT 优先；净偏移按 100/300 µm 三分。"""
    if faulted or offset_um is None:
        return "FAIL"
    a = abs(offset_um)
    if a > OFFSET_FAIL_UM:
        return "FAIL"
    if a <= OFFSET_PASS_UM:
        return "PASS"
    return "MARGIN"


def combine_verdicts(verdicts):
    """只有全部已完成段均 PASS 才可行；调用者还须核对计划段数。"""
    if verdicts and all(v == "PASS" for v in verdicts):
        return True, "可行"
    return False, "不可行或未完成"


def reached(vx_mm_s, target_v):
    """加速到达判据：固件速度估计带噪声（σ≤5）与 ≤10 ms 群延迟，
    容差取 max(2σ, 目标的 5%)。"""
    if target_v != 0 and vx_mm_s * target_v <= 0:
        return False
    return abs(vx_mm_s - target_v) <= max(2 * VX_NOISE_SIGMA, abs(target_v) * 0.05)


def settled_run(vx_samples, run=SETTLE_RUN):
    """停稳判定：连续 run 个样本 |vx| ≤ 2σ。输入为最近样本序列（旧→新），
    list 或 deque 均可（deque 不支持切片，先转 list）。"""
    if len(vx_samples) < run:
        return False
    return all(abs(v) <= VX_SETTLED for v in list(vx_samples)[-run:])


def leg_times(v, acc, hold_s):
    """超时预算：斜坡时间 v/acc（s，均为 mm 单位制）加裕量。"""
    ramp = abs(v) / float(acc)
    return ramp + 0.5, ramp + 1.0   # (到达超时, 停稳超时)


def hold_time(v):
    """该速度点的巡航保持时间（方案单段时序表）。未知速度点线性内插。"""
    if v in LEG_PROFILE:
        return LEG_PROFILE[v][1]
    ks = sorted(LEG_PROFILE)
    lo, hi = ks[0], ks[-1]
    if v <= lo:
        return LEG_PROFILE[lo][1]
    if v >= hi:
        return LEG_PROFILE[hi][1]
    for a, b in zip(ks, ks[1:]):
        if a <= v <= b:
            fa, fb = LEG_PROFILE[a][1], LEG_PROFILE[b][1]
            return fa + (fb - fa) * (v - a) / (b - a)
    raise ValueError(v)


# ---- 串口会话扩展 ----

class TestRig(Rig):
    """Rig 之上加：带时间戳状态采样、FAULT 事件、原始行日志。"""

    def __init__(self, port, baud=460800, log_path=None):
        super().__init__(port, baud, timeout=0.01)
        self.ser.write_timeout = 0.2
        self.samples = deque(maxlen=600000)   # (t, x_um, theta_urad, vx, vth)
        self.fault_events = []                # [(t, reason)]
        self._t0 = time.monotonic()
        self._log = open(log_path, "a", encoding="ascii") if log_path else None

    def now(self):
        return time.monotonic() - self._t0

    def _dispatch(self, line):
        if self._log:
            self._log.write("%.3f %s\n" % (self.now(), line))
        super()._dispatch(line)
        parts = line.split()
        if len(parts) == 5 and parts[0] == "STATE":
            try:
                x, th, vx, vth = (int(p) for p in parts[1:])
            except ValueError:
                return
            self.samples.append((time.monotonic(), x, th, vx, vth))
        elif len(parts) == 3 and parts[0] == "MODE" and parts[1] == "FAULT":
            self.fault_events.append((time.monotonic(), parts[2]))

    def last_state_tuple(self):
        """最近一帧 (x_um, vx_mm_s)；无样本返回 None。"""
        if not self.samples:
            return None
        _, x, _, vx, _ = self.samples[-1]
        return x, vx

    def close(self):
        try:
            if self._log:
                self._log.flush()
                self._log.close()
        finally:
            super().close()


# ---- 会话操作 ----

class ExperimentAborted(RuntimeError):
    """当前试验没有完整证据或发生异常，禁止自动恢复运动。"""


# 这是主机接收新鲜度限制，不是固件采样延迟保证。
STATE_MAX_AGE_S = 0.1


def checked_state(rig):
    if rig.last_mode != ("READY", "NONE"):
        raise ExperimentAborted("mode=%s" % (rig.last_mode,))
    if not rig.samples:
        raise ExperimentAborted("missing-state")
    sample = rig.samples[-1]
    if time.monotonic() - sample[0] > STATE_MAX_AGE_S:
        raise ExperimentAborted("stale-state")
    return sample


def request_stop(rig):
    """仅尝试请求斜坡停；发送成功不等于实际停稳，失败交由看门狗兜底。"""
    try:
        rig.send_line("VEL 0")
        return True
    except (OSError, RuntimeError) as exc:
        print("停止命令未能发送：%s；请使用独立停机手段。" % exc, file=sys.stderr)
        return False


def ensure_ready(rig, timeout=5.0):
    # 禁止用前一次查询缓存的 READY 作为本次授权依据。
    rig.last_mode = None
    m = rig.query()
    if m == ("READY", "NONE"):
        checked_state(rig)
        return True
    print("当前模式 %s，非 READY；完成手动标定并单独确认 ENABLE 后再试验。" % (m,))
    return False


def set_config(rig, name, value):
    rig.last_reply = None
    rig.send_line("CONFIG %s %d" % (name, value))
    rig.pump(0.5)
    r = rig.last_reply
    if r == ("OK", name, value):
        return True
    print("CONFIG %s %d 未确认（%s）" % (name, value, r))
    return False


def move_to_center(rig, band_um=2000, v_slow=100, timeout_s=20.0):
    """人工已确认行程后回中；失败只停机，不 RESET/ENABLE。"""
    t_end = time.monotonic() + timeout_s
    try:
        while time.monotonic() < t_end:
            _, x, _, vx, _ = checked_state(rig)
            if abs(x) <= band_um:
                stopped = wait_until_settled(rig, min(1.0, t_end - time.monotonic()))
                if abs(stopped[1]) <= band_um:
                    return True
                continue
            rig.send_line("VEL %d" % (-v_slow if x > 0 else v_slow))
            rig.pump(FEED_PERIOD_S)
        raise ExperimentAborted("center-timeout")
    finally:
        if not request_stop(rig) and sys.exc_info()[0] is None:
            raise ExperimentAborted("stop-send-failed")


# ---- 段执行 ----

def wait_until_settled(rig, timeout_s):
    """发送零速，等待不同接收帧构成的连续停稳证据。"""
    deadline = time.monotonic() + timeout_s
    vx_run = deque(maxlen=SETTLE_RUN)
    last_stamp = checked_state(rig)[0]
    while time.monotonic() < deadline:
        rig.send_line("VEL 0")
        rig.pump(FEED_PERIOD_S)
        sample = checked_state(rig)
        if sample[0] <= last_stamp:
            continue
        last_stamp = sample[0]
        vx_run.append(sample[3])
        if settled_run(vx_run):
            return sample
    raise ExperimentAborted("settle-timeout")


def run_leg(rig, v, hold_s, acc):
    """单程完整到速、巡航、停稳才返回；异常抛出且请求停机。"""
    reach_to, stop_to = leg_times(v, acc, hold_s)
    try:
        sample = checked_state(rig)
        x_start = sample[1]
        if abs(sample[3]) > VX_SETTLED:
            raise ExperimentAborted("not-at-rest")
        deadline = time.monotonic() + reach_to
        hold_end = None
        while True:
            checked_state(rig)
            if hold_end is None and time.monotonic() >= deadline:
                raise ExperimentAborted("reach-timeout")
            if hold_end is not None and time.monotonic() >= hold_end:
                break
            rig.send_line("VEL %d" % v)
            rig.pump(FEED_PERIOD_S)
            sample = checked_state(rig)
            if hold_end is None and reached(sample[3], v):
                hold_end = time.monotonic() + hold_s

        sample = wait_until_settled(rig, stop_to)
        return x_start, sample[1], False, True, ""
    finally:
        if not request_stop(rig) and sys.exc_info()[0] is None:
            raise ExperimentAborted("stop-send-failed")


def run_segment(rig, v, acc):
    """两程完整才判定净偏移；任何异常或不完整段中止本组合。"""
    legs = []
    note = ""
    fault_count = len(rig.fault_events)
    try:
        for direction in (+1, -1):
            r = run_leg(rig, direction * v, hold_time(v), acc)
            legs.append(r)
            if r[2] or not r[3] or r[0] is None or r[1] is None:
                raise ExperimentAborted(r[4] or "incomplete-leg")
    except ExperimentAborted as exc:
        note = str(exc)
        request_stop(rig)
    faulted = len(rig.fault_events) > fault_count or any(l[2] for l in legs)
    complete = len(legs) == 2 and not note
    offset = legs[-1][1] - legs[0][0] if complete else None
    return {
        "v_mm_s": v, "acc_mm_s2": acc, "offset_um": offset,
        "verdict": classify_offset(offset, faulted), "faulted": faulted,
        "aborted": not complete, "notes": note,
    }


# ---- 子命令 ----

def cmd_calib(rig, args):
    rig.last_mode = None
    if rig.query() != ("DISABLED", "NONE"):
        print("标定需要 DISABLED；不会自动清故障或关闭使能。")
        return 1
    for command, reply, prompt in (
        ("MARK LEFT", "MARK_LEFT", "手推至左标定点，停稳后按回车 …"),
        ("MARK RIGHT", "MARK_RIGHT", "手推至右标定点，停稳后按回车 …"),
    ):
        input(prompt)
        rig.last_reply = None
        rig.send_line(command)
        rig.pump(1.0)
        r = rig.last_reply
        if not (r and r[0] == "OK" and r[1] == reply):
            print("%s 未确认：%s" % (command, r))
            return 1
    # MARK_RIGHT 返回的就是 L，不是右端的累计编码器读数。
    print("标定行程 L = %d µm（%.1f mm）；请用尺量核对。" % (r[2], r[2] / 1000.0))
    print("保持 DISABLED。核对行程与独立停机条件后，另行决定是否 ENABLE。")
    return 0


def cmd_smoke(rig, args):
    if not ensure_ready(rig):
        return 1
    if not set_config(rig, "ACC_MAX", 5000):
        return 1
    seg = run_segment(rig, 50, 5000)
    print("冒烟段：%s（净偏移 %s µm，备注 %s）" %
          (seg["verdict"], seg["offset_um"], seg["notes"] or "无"))
    return 0 if seg["verdict"] == "PASS" else 1


def cmd_matrix(rig, args):
    if not ensure_ready(rig):
        return 1
    rows = []
    aborted = True
    try:
        for v in args.speeds:
            move_to_center(rig)
            for acc in args.accs:
                if not set_config(rig, "ACC_MAX", acc):
                    raise ExperimentAborted("config-unconfirmed")
                for rep in range(args.reps):
                    seg = run_segment(rig, v, acc)
                    seg.update(seq=rep + 1)
                    rows.append(seg)
                    print("v=%d acc=%d 段%d：%s 偏移=%s %s" %
                          (v, acc, rep + 1, seg["verdict"], seg["offset_um"], seg["notes"]))
                    if seg["verdict"] != "PASS" or seg["aborted"]:
                        raise ExperimentAborted("segment-not-pass")
        aborted = False
    except ExperimentAborted as exc:
        print("矩阵中止：%s；不会自动恢复或继续下一档。" % exc)
    finally:
        stop_failed = not request_stop(rig)
        aborted = aborted or stop_failed
        write_segments_csv(os.path.join(args.outdir, "segments.csv"), rows)
        write_summary(os.path.join(args.outdir, "summary.txt"), rows, args, aborted)
        if stop_failed and sys.exc_info()[0] is None:
            raise ExperimentAborted("stop-send-failed")
    print("结果已写入 %s" % args.outdir)
    return 1 if aborted else 0


def cmd_step_response(rig, args):
    """记录每一帧主机接收时间；不把接收时间当作设备采样时钟。"""
    if not ensure_ready(rig):
        return 1
    if not set_config(rig, "ACC_MAX", 5000):
        return 1
    path = os.path.join(args.outdir, "step-response.csv")
    cursor = len(rig.samples)
    try:
        # 起步前先证明停稳；结束停稳检查与往返试验复用同一契约。
        wait_until_settled(rig, 1.0)
        run_leg(rig, args.step_v, 3.0, 5000)
        print("阶跃接收记录写入 %s；需评估串口缓冲和时钟误差后再辨识。" % path)
        return 0
    finally:
        stop_failed = not request_stop(rig)
        # 整段有界，远小于 samples 容量；异常时也保留已收到的每一帧。
        with open(path, "w", newline="", encoding="ascii") as f:
            w = csv.writer(f)
            w.writerow(["host_rx_t_s", "x_um", "vx_mm_s"])
            for t, x, _, vx, _ in list(rig.samples)[cursor:]:
                w.writerow(["%.6f" % (t - rig._t0), x, vx])
        if stop_failed and sys.exc_info()[0] is None:
            raise ExperimentAborted("stop-send-failed")


# ---- 输出 ----

def write_segments_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["v_mm_s", "acc_mm_s2", "seq", "verdict",
                    "offset_um", "faulted", "notes"])
        for r in rows:
            w.writerow([r["v_mm_s"], r["acc_mm_s2"], r.get("seq", ""),
                        r["verdict"], r["offset_um"] if r["offset_um"] is not None else "",
                        int(r["faulted"]), r["notes"]])


def write_summary(path, rows, args, aborted):
    combos = {}
    for r in rows:
        combos.setdefault((r["v_mm_s"], r["acc_mm_s2"]), []).append(r["verdict"])
    with open(path, "w", encoding="utf-8") as f:
        f.write("速度×加速度试验记录（电气与机械条件须另行记录）\n")
        f.write("日期：%s  中止：%s\n\n" % (time.strftime("%Y-%m-%d %H:%M"),
                                        "是" if aborted else "否"))
        f.write("v\\acc    " + "".join("%-8d" % a for a in args.accs) + "\n")
        for v in args.speeds:
            cells = []
            for a in args.accs:
                vs = combos.get((v, a))
                if not vs:
                    cells.append("%-8s" % "—")
                    continue
                ok = len(vs) == args.reps and combine_verdicts(vs)[0]
                cells.append("%-8s" % ("可行" if ok else "不可行"))
            f.write("%-8d" % v + "".join(cells) + "\n")
        f.write("\n每速度点完整通过主机检查的最高已测加速度（不是机械极限）：\n")
        for v in args.speeds:
            best = None
            for a in args.accs:
                vs = combos.get((v, a))
                if vs and len(vs) == args.reps and combine_verdicts(vs)[0]:
                    best = a
            if best is None:
                f.write("  %d mm/s：没有完整全过档位\n" % v)
            else:
                f.write("  %d mm/s：%d mm/s²\n" % (v, best))


def main():
    ap = argparse.ArgumentParser(description="最大加速度实测执行器")
    ap.add_argument("--port", required=True, help="串口（如 COM7）")
    ap.add_argument("--baud", type=int, default=460800)
    ap.add_argument("--out", default=None, help="结果目录（默认 results/maxaccel-<ts>/）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("calib")
    sub.add_parser("smoke")
    p = sub.add_parser("matrix")
    p.add_argument("--speeds", type=int, nargs="+", default=SPEEDS_DEFAULT)
    p.add_argument("--accs", type=int, nargs="+", default=ACCS_DEFAULT)
    p.add_argument("--reps", type=int, default=REPS_DEFAULT)
    p = sub.add_parser("step-response")
    p.add_argument("--step-v", type=int, default=50)

    args = ap.parse_args()
    if args.cmd == "matrix":
        for name in ("speeds", "accs"):
            values = getattr(args, name)
            if any(v <= 0 for v in values) or values != sorted(set(values)):
                ap.error("%s 必须为严格递增的正整数列表" % name)
        if args.reps <= 0:
            ap.error("reps 必须大于 0")
    if args.cmd == "step-response" and args.step_v <= 0:
        ap.error("step-v 必须大于 0")
    outdir = args.out or os.path.join(
        "results", "maxaccel-" + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(outdir, exist_ok=True)
    log_path = os.path.join(outdir, "raw.log")
    rig = TestRig(args.port, args.baud, log_path=log_path)
    table = {"calib": cmd_calib, "smoke": cmd_smoke,
             "matrix": cmd_matrix, "step-response": cmd_step_response}
    args.outdir = outdir
    rc = 1
    try:
        rc = table[args.cmd](rig, args)
    except KeyboardInterrupt:
        print("\n用户中断；已跑数据保留在 %s" % outdir)
        rc = 130
    except (ExperimentAborted, OSError) as exc:
        print("试验中止：%s" % exc, file=sys.stderr)
        rc = 1
    finally:
        try:
            if args.cmd != "calib" and not request_stop(rig) and rc == 0:
                rc = 1
        finally:
            rig.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
