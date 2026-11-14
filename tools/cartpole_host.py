#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cartpole_host — cartpole 固件串口联调工具（PC 直连 ESP32-S3 UART1/CH343P）

依赖：pip install pyserial

用法（示例）：
  python cartpole_host.py --port COM7 query
  python cartpole_host.py --port COM7 mark-left    # 小车推到最左端后
  python cartpole_host.py --port COM7 mark-right   # 小车推到最右端后
  python cartpole_host.py --port COM7 enable
  python cartpole_host.py --port COM7 vel 200 --hold 2
  python cartpole_host.py --port COM7 config VEL_MAX 800
  python cartpole_host.py --port COM7 dump
  python cartpole_host.py --port COM7 state --secs 10
  python cartpole_host.py --port COM7 wdt-test
  python cartpole_host.py --port COM7 console

对应 protocol.md：STATE/MODE/OK/ERR 行、460800 8N1。
"""

import argparse
import math
import sys
import time

import serial
from velocity_validity import VelocityValidity


class Rig:
    def __init__(self, port, baud=460800, timeout=0.2, *,
                 serial_factory=None, clock=None, output=None):
        """创建会话。可注入兼容 pyserial 的工厂、单调秒时钟和消息输出函数。

        会话负责关闭工厂返回的串口。工厂接收 port、baud、timeout 和
        write_timeout；时钟必须单调递增，读取等待时间也应计入时钟。
        """
        self._clock = clock if clock is not None else time.monotonic
        self._output = output if output is not None else print
        factory = serial_factory if serial_factory is not None else serial.Serial
        self.ser = factory(port, baud, timeout=timeout, write_timeout=.02)
        self.velocity_validity = VelocityValidity(self._clock)
        self.state_received_at = None
        self.last_state = None     # 首帧合法 STATE 到来前尚无遥测
        self.last_mode = None      # (mode, reason)
        self.last_reply = None     # (kind, name, value)
        self.replies = {}          # 本次请求的命名 OK 回执
        self.state_count = 0
        self.unknown_count = 0
        # 跨 pump 调用持久的接收缓冲：未凑齐的半行必须留到下次继续，
        # 不得随窗口丢弃——STATE 流近乎连续，0.2 s 窗口边界几乎必然
        # 落在行中间（丢半行头 + 下一窗口把行尾记成 UNKNOWN）
        self._rx_buf = b""
        # 丢弃到首个 \n 的残余（mid-stream 半行/开串口毛刺不是链路
        # 质量问题，不计入 UNKNOWN），保留 \n 之后已开始的行
        t0 = self._clock()
        while self._clock() - t0 < 0.5:
            chunk = self.ser.read(256)
            if chunk:
                self._rx_buf += chunk
                if b"\n" in self._rx_buf:
                    self._rx_buf = self._rx_buf.split(b"\n", 1)[1]
                    break

    def close(self):
        self.ser.close()

    def state_is_fresh(self, max_age=0.1):
        """最近接收的状态仍在接收时效内；不等同于设备采样时间。"""
        return (self.last_state is not None and self.state_received_at is not None
                and 0 <= self._clock() - self.state_received_at <= max_age)

    def send_line(self, line):
        self.velocity_validity.command(line)
        if line.startswith("VEL ") and line.split()[1:] != ["0"]:
            if not self.state_is_fresh():
                self.velocity_validity.failed = True
                raise RuntimeError("没有最近收到的状态；禁止非零速度")
        data = (line + "\n").encode("ascii")
        if self.ser.write(data) != len(data):
            self.velocity_validity.failed = True
            raise RuntimeError("串口写入不完整")

    def pump(self, duration):
        """读串口 duration 秒，解析 STATE/MODE/OK/ERR，统计 UNKNOWN。"""
        t0 = self._clock()
        while self._clock() - t0 < duration:
            chunk = self.ser.read(256)
            if not chunk:
                continue
            self._rx_buf += chunk
            while b"\n" in self._rx_buf:
                raw, self._rx_buf = self._rx_buf.split(b"\n", 1)
                line = raw.decode("ascii", "replace").strip()
                if not line:
                    continue
                self._dispatch(line)
                if self.velocity_validity.active and self.velocity_validity.failed:
                    raise RuntimeError("活动会话收到失效或损坏数据；停止运动")

    def _unknown(self, line):
        self.unknown_count += 1
        if self.velocity_validity.active:
            self.velocity_validity.failed = True
            self.last_state = None
            self.state_received_at = None
            # 交由运动门禁中止；在零速请求前不得阻塞于stdout。
        else:
            self._output("[UNKNOWN] %r" % line)

    def _dispatch(self, line):
        if line.split()[:1] == ["VEL_VALID"]:
            if not self.velocity_validity.update(line.split()):
                self.last_state = None
                self.state_received_at = None
            return
        if line.startswith("STATE "):
            parts = line.split()
            if len(parts) == 5:
                try:
                    [int(p) for p in parts[1:]]
                    self.state_count += 1
                    if self.velocity_validity.received_at is None or self.velocity_validity.ready():
                        self.last_state = parts[1:]
                        self.state_received_at = self._clock()
                    return
                except ValueError:
                    pass
            self._unknown(line)
        elif line.startswith("MODE "):
            parts = line.split()
            if len(parts) == 3:
                self.last_mode = (parts[1], parts[2])
                self._output("[MODE] %s %s" % self.last_mode)
            else:
                self._unknown(line)
        elif line.startswith("OK "):
            parts = line.split()
            if len(parts) == 3:
                try:
                    self.last_reply = ("OK", parts[1], int(parts[2]))
                    self.replies[parts[1]] = int(parts[2])
                    self._output("[OK] %s = %d" % (parts[1], int(parts[2])))
                    return
                except ValueError:
                    pass
            self._unknown(line)
        elif line.startswith("ERR "):
            self.last_reply = ("ERR", line[4:], None)
            self._output("[ERR] %s" % line[4:])
        else:
            self._unknown(line)

    def query(self):
        self.send_line("QUERY")
        self.pump(0.3)
        return self.last_mode

    def wait_mode(self, want, timeout):
        t0 = self._clock()
        while self._clock() - t0 < timeout:
            self.pump(0.1)
            if self.last_mode and self.last_mode[0] == want:
                return self.last_mode
        return None


def cmd_query(rig, args):
    m = rig.query()
    if m is None:
        print("无 MODE 应答")
        return 1
    return 0


def cmd_disable(rig, args):
    rig.last_mode = None
    rig.last_reply = None
    rig.send_line("DISABLE")
    rig.pump(0.5)
    if rig.last_mode == ("DISABLED", "NONE"):
        return 0
    print("DISABLE 未确认：MODE=%s，回执=%s。BUSY 时先 VEL 0 并观察停稳；FAULT 保留原故障。" % (rig.last_mode, rig.last_reply))
    return 1


def cmd_reset(rig, args):
    rig.send_line("RESET")
    rig.pump(0.3)
    m = rig.last_mode
    if m and m[0] == "DISABLED":
        print("RESET → DISABLED")
        return 0
    print("RESET 未生效（当前 %s；仅 FAULT 时有效。READY 下先发送 VEL 0，观察停稳后使用 disable；不要手推制造故障。）" % (m,))
    return 1


def cmd_mark(rig, args, word):
    rig.send_line(word)
    rig.pump(1.0)
    r = rig.last_reply
    if r and r[0] == "OK":
        print("%s → %d" % (r[1], r[2]))
        return 0
    print("%s 被拒（%s）" % (word, r[1] if r else "无回执"))
    return 1


def cmd_mark_left(rig, args):
    return cmd_mark(rig, args, "MARK LEFT")


def cmd_mark_right(rig, args):
    return cmd_mark(rig, args, "MARK RIGHT")


def cmd_confirm_left(rig, args):
    rig.last_reply = None
    rig.send_line("CONFIRM LEFT")
    rig.pump(1.0)
    r = rig.last_reply
    if r and r[:2] == ("OK", "CONFIRM_LEFT"):
        print("左参考已确认，仍保持 DISABLED；当前位置 %d µm" % r[2])
        return 0
    print("左参考未确认：%s" % (r or "无回执（检查固件是否支持）",))
    return 1


def cmd_calib_status(rig, args):
    rig.last_reply = None
    rig.replies.clear()
    rig.send_line("CALIB?")
    rig.pump(1.0)
    expected = {"CAL_STATE", "CAL_LENGTH_UM", "CAL_SAVED", "CAL_STORAGE"}
    if not expected.issubset(rig.replies):
        print("标定状态回执不完整，请重试；不能据此判断可使能。")
        return 1
    return 0


def cmd_enable(rig, args):
    rig.query()  # 等待固件的有效性心跳；未知时不使能。
    rig.send_line("ENABLE")
    m = rig.wait_mode("READY", args.timeout)
    if m is None:
        print("超时未到 READY（当前 %s）" % (rig.last_mode,))
        return 1
    return 0


def cmd_vel(rig, args):
    m = rig.query()
    if not m or m[0] != "READY":
        print("当前模式 %s，非 READY——先标定并 ENABLE" % (m,))
        return 1
    end = time.time() + args.hold
    n = 0
    while time.time() < end:
        rig.send_line("VEL %d" % args.v)
        n += 1
        rig.pump(0.005)
    rig.pump(0.3)
    print("已发送 %d 条 VEL（%.1f Hz）" % (n, n / args.hold))
    if rig.last_state:
        x, th, vx, vth = rig.last_state
        print("最新 STATE: x=%s（%.2f mm） θ=%s（%.2f°） vx=%s mm/s vth=%s mrad/s"
              % (x, int(x) / 1000.0, th, int(th) / 17453.3, vx, vth))
    return 0


def cmd_config(rig, args):
    rig.send_line("CONFIG %s %d" % (args.name.upper(), args.value))
    rig.pump(0.5)
    if rig.last_reply and rig.last_reply[0] == "OK":
        return 0
    return 1


def cmd_dump(rig, args):
    rig.state_count = 0
    rig.send_line("CONFIG?")
    rig.pump(0.8)
    print("STATE 行（dump 窗口内）：%d" % rig.state_count)
    return 0


def cmd_state(rig, args):
    t0 = time.time()
    rig.state_count = 0
    rig.unknown_count = 0
    xs, ths = [], []
    while time.time() - t0 < args.secs:
        rig.pump(0.2)
        if rig.last_state and rig.state_is_fresh():
            x, th = int(rig.last_state[0]), int(rig.last_state[1])
            xs.append(x)
            ths.append(th)
    dt = time.time() - t0
    rate = rig.state_count / dt
    print("时长 %.1f s，STATE %d 行 → %.1f Hz" %
          (dt, rig.state_count, rate))
    print("UNKNOWN 行：%d（要求 0）" % rig.unknown_count)
    if xs:
        print("x_um ∈ [%d, %d]（漂移 %d µm；x ≈ %.2f mm）" %
              (min(xs), max(xs), max(xs) - min(xs),
               (min(xs) + max(xs)) / 2000.0))
        # θ 逐端换算：±π 环绕边界处 min/max 会分居两侧，取均值无意义
        print("theta_urad ∈ [%d, %d]（θ ∈ [%.2f°, %.2f°]）" %
              (min(ths), max(ths),
               min(ths) / 17453.3, max(ths) / 17453.3))
    expected = getattr(args, "expected_hz", None)
    rate_ok = expected is None or abs(rate - expected) <= 1.0
    if expected is not None:
        print("目标 %.1f Hz（容差 ±1 Hz）：%s" %
              (expected, "通过" if rate_ok else "未通过"))
    else:
        print("未指定目标频率，仅检查有数据且 UNKNOWN 为 0。")
    ok = rig.state_count > 0 and rate_ok and rig.unknown_count == 0
    return 0 if ok else 1


def cmd_wdt_test(rig, args):
    m = rig.query()
    if not m or m[0] != "READY":
        print("需先标定并 ENABLE 到 READY")
        return 1
    end = time.time() + 1.0
    while time.time() < end:
        rig.send_line("VEL 200")
        rig.pump(0.005)
    print("停止喂狗，观察 1 s …")
    rig.pump(1.0)
    m = rig.query()
    print("QUERY → %s（预期 READY：看门狗是瞬态保护不改模式）" % (m,))
    ok = m and m[0] == "READY" and m[1] == "NONE"
    return 0 if ok else 1


def cmd_console(rig, args):
    print("交互模式：输入命令回车发送；Ctrl-C 退出。")
    try:
        while True:
            line = input("> ").strip()
            if line:
                rig.send_line(line)
            rig.pump(0.3)
    except KeyboardInterrupt:
        pass
    return 0


def main():
    ap = argparse.ArgumentParser(description="cartpole 固件串口联调工具")
    ap.add_argument("--port", required=True, help="串口（如 COM7）")
    ap.add_argument("--baud", type=int, default=460800)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("query")
    sub.add_parser("mark-left")
    sub.add_parser("mark-right")
    sub.add_parser("confirm-left")
    sub.add_parser("calib-status")
    p = sub.add_parser("enable"); p.add_argument("--timeout", type=float, default=5.0)
    p = sub.add_parser("vel"); p.add_argument("v", type=int)
    p.add_argument("--hold", type=float, default=1.0)
    p = sub.add_parser("config"); p.add_argument("name"); p.add_argument("value", type=int)
    sub.add_parser("dump")
    p = sub.add_parser("state"); p.add_argument("--secs", type=float, default=10.0)
    p.add_argument("--expected-hz", type=float, help="预期 STATE 频率，容差 ±1 Hz；省略时仅报告实测频率")
    sub.add_parser("wdt-test")
    sub.add_parser("console")
    sub.add_parser("reset")
    sub.add_parser("disable")

    args = ap.parse_args()
    if args.cmd == "state":
        if not math.isfinite(args.secs) or args.secs <= 0:
            ap.error("--secs 必须是正的有限秒数")
        if args.expected_hz is not None and (
                not math.isfinite(args.expected_hz) or args.expected_hz <= 0):
            ap.error("--expected-hz 必须是正的有限频率")
    rig = Rig(args.port, args.baud)
    try:
        table = {
            "confirm-left": cmd_confirm_left, "calib-status": cmd_calib_status,
            "query": cmd_query, "mark-left": cmd_mark_left,
            "mark-right": cmd_mark_right, "enable": cmd_enable, "vel": cmd_vel,
            "config": cmd_config, "dump": cmd_dump, "state": cmd_state,
            "wdt-test": cmd_wdt_test, "console": cmd_console,
            "reset": cmd_reset, "disable": cmd_disable,
        }
        rc = table[args.cmd](rig, args)
    except (RuntimeError, OSError, KeyboardInterrupt) as exc:
        stop_error = None
        if rig.velocity_validity.active:
            try:
                rig.send_line("VEL 0")
            except (OSError, RuntimeError) as error:
                stop_error = error
        print("命令中止：%s" % exc)
        if stop_error is not None:
            print("零速请求失败：%s；请使用独立断电。" % stop_error)
        rc = 1
    finally:
        rig.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
