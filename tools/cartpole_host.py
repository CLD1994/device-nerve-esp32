#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cartpole_host — cartpole 固件串口联调工具（PC 直连 ESP32-S3 UART0（3.3 V TTL））

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

对应 docs/protocol.md。工具默认 460800，须通过 --baud 匹配固件实际配置。
"""

from collections import deque
import argparse
import math
import re
import sys
import time

from velocity_validity import VelocityValidity
from session_timing import SessionTiming
from state_frame import parse_state_frame


class Rig:
    def __init__(self, port, baud=460800, timeout=0.2, *,
                 serial_factory=None, clock=None, output=None, step_loss_policy="report"):
        """创建会话。可注入兼容 pyserial 的工厂、单调秒时钟和消息输出函数。

        会话负责关闭工厂返回的串口。工厂接收 port、baud、timeout 和
        write_timeout；时钟必须单调递增，读取等待时间也应计入时钟。
        """
        if step_loss_policy not in ("report", "stop"):
            raise ValueError("step_loss_policy 必须为 report 或 stop")
        self.step_loss_policy = step_loss_policy
        self.last_step_loss_event = None
        self.event_count = 0
        self._clock = clock if clock is not None else time.monotonic
        self._output = output if output is not None else print
        if serial_factory is None:
            import serial
            serial_factory = serial.Serial
        factory = serial_factory
        self.ser = factory(port, baud, timeout=timeout, write_timeout=.02)
        self.velocity_validity = VelocityValidity(self._clock)
        self.state_received_at = None
        self.last_state = None     # 首帧合法 STATE 到来前尚无遥测
        self.last_mode = None      # (mode, reason)
        self.last_reply = None     # (kind, name, value)
        self.replies = {}          # 本次请求的命名 OK 回执
        self.state_count = 0
        self.state_observer = None
        self.message_observer = None
        self.max_rx_waiting = 0
        self.timing = None
        self.stop_observation = None
        self.unknown_count = 0
        self.first_failure = None
        self._raw_context = deque(maxlen=4)
        self._current_raw = None
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

    def note_failure(self, reason, current_raw=False, **measurements):
        """有界旁路首因；不改变门禁，不在控制路径格式化或打印。"""
        if self.first_failure is not None:return
        current=self._current_raw if current_raw else None
        self.first_failure=dict(reason=reason,
            observed_monotonic_s=current[0] if current is not None else self._clock(),
            raw=None if current is None else current[1],
            raw_total=0 if current is None else current[2],context=tuple(self._raw_context),measurements=measurements)

    def note_velocity_gate(self):
        v=self.velocity_validity
        if v.failed:self.note_failure('existing_failure_latch')
        elif v.age() is None:self.note_failure('measurement_missing')
        elif not 0<=v.age()<=.1:self.note_failure('measurement_expired',age_s=v.age())
        elif not v.ready():self.note_failure('measurement_invalid')

    def failure_summary(self):
        e=self.first_failure
        if e is None:return None
        labels={'measurement_invalid':'STATE所需测量通道无效','measurement_missing':'尚未收到完整有效STATE','measurement_expired':'STATE观测年龄超限','measurement_gate_error':'STATE测量门禁异常', 'invalid_velocity_fields':'速度有效性心跳字段错误',
                'invalid_velocity_flags':'速度窗口报告无效',
                'velocity_heartbeat_expired':'速度有效性心跳超时或时间无效',
                'velocity_heartbeat_missing':'尚未收到速度有效性心跳',
                'velocity_flags_not_ready':'速度有效性条件未就绪',
                'existing_failure_latch':'发现此前已经锁存的失败，触发点未记录',
                'unknown_line':'未知接收行', 'short_write':'串口写入不完整',
                'read_exception':'串口读取异常','write_exception':'串口写入异常',
                'serial_backlog_limit':'串口待接收积压超限','receive_buffer_limit':'接收缓冲超限',
                'state_missing_or_expired':'状态缺失或接收年龄超限',
                'user_interrupt':'用户中断（Ctrl+C）'}
        lines=['首个主机诊断：%s（%s）；主机读取/发现单调时间 %.6f s（不是设备发送时间）'%
               (labels.get(e['reason'],'主机条件触发，见分类'),e['reason'],e['observed_monotonic_s'])]
        if e['measurements']:
            lines.append('条件数值：'+', '.join('%s=%s'%(key,value) for key,value in e['measurements'].items()))
        def raw_text(raw,total):
            return repr(raw)+(' [截断，原长%d字节]'%total if total>len(raw) else '')
        lines.append('原始行：'+('无原始行；仅发现本地条件/既有锁存' if e['raw'] is None else raw_text(e['raw'],e['raw_total'])))
        for stamp,raw,total in e['context']:
            lines.append('前文 %.6f s：%s'%(stamp,raw_text(raw,total)))
        return '\n'.join(lines)

    def clear_motion_state(self):
        self.last_state=self.state_received_at=None

    def begin_stop_observation(self):
        old=self.stop_observation or self.velocity_validity
        self.stop_observation=old.stopped_copy()
        self.clear_motion_state()

    def _invalidate_stop_observation(self):
        if self.stop_observation is not None:self.begin_stop_observation()

    def end_stop_observation(self):
        self.stop_observation = None

    def close(self):
        self.ser.close()

    def state_is_fresh(self, max_age=0.1):
        gate=self.stop_observation or self.velocity_validity
        age=gate.age()
        return self.last_state is not None and age is not None and 0<=age<=max_age

    def on_measurement_frame(self, frame):
        pass

    def accept_measurement_frame(self, frame):
        cart,pole=frame['cart'],frame['pole']
        self.last_state=[str(cart['x_um']),str(pole['theta_urad']),str(cart['vx_mm_s']),str(pole['vth_mrad_s'])]
        self.state_received_at=(self.stop_observation or self.velocity_validity).received_at
        self.state_count+=1
        if self.timing is not None:self.timing.state(cart['vx_mm_s'])
        if self.state_observer is not None:self.state_observer()

    def send_line(self, line):
        words=line.split()
        if words and (words[0]=='ENABLE' or (words[0]=='VEL' and words[1:]!=['0'])):
            self.note_velocity_gate()
        self.velocity_validity.command(line)
        if line.startswith("VEL ") and line.split()[1:] != ["0"]:
            if not self.state_is_fresh():
                self.note_failure("state_missing_or_expired")
                self.velocity_validity.failed = True
                raise RuntimeError("没有最近收到的状态；禁止非零速度")
        data = (line + "\n").encode("ascii")
        match = re.fullmatch(r'VEL ([+-]?[0-9]+)', line) if self.timing is not None else None
        velocity = int(match[1]) if match is not None and len(match[1]) <= 12 else None
        if self.timing is not None and velocity is not None:self.timing.write_attempt(velocity)
        try:
            written=self.ser.write(data)
        except (OSError,RuntimeError):
            self.note_failure('write_exception')
            raise
        if written != len(data):
            self.note_failure('short_write')
            self.velocity_validity.failed = True
            raise RuntimeError("串口写入不完整")
        if self.timing is not None and velocity is not None:self.timing.write_complete(velocity)

    def pump(self, duration):
        """读串口 duration 秒，解析 STATE/MODE/OK/ERR，统计 UNKNOWN。"""
        t0 = self._clock()
        while self._clock() - t0 < duration:
            try:
                chunk = self.ser.read(256)
            except OSError:
                self.note_failure('read_exception')
                raise
            if not chunk:
                continue
            self._consume(chunk)

    def _consume(self, chunk):
        self._rx_buf += chunk
        if len(self._rx_buf) > 65536:
            self.note_failure('receive_buffer_limit')
            self.velocity_validity.failed = True
            self._invalidate_stop_observation()
            raise RuntimeError("接收缓冲超过上限")
        while b"\n" in self._rx_buf:
            raw, self._rx_buf = self._rx_buf.split(b"\n", 1)
            line = raw.decode("ascii", "replace").removesuffix("\r")
            if not line:
                continue
            self._current_raw=(self._clock(),raw[:256],len(raw))
            try:
                if self.velocity_validity.active and self.velocity_validity.failed:
                    self.note_failure('existing_failure_latch')
                if self.message_observer is not None:
                    self.message_observer(line)
                try:
                    self._dispatch(line)
                except RuntimeError:
                    self.note_failure('receive_callback_or_stop_observation_error',current_raw=True)
                    self._invalidate_stop_observation()
                    raise
                if self.stop_observation is None and self.velocity_validity.active and self.velocity_validity.failed:
                    self.note_failure('existing_failure_latch')
                    raise RuntimeError("活动会话收到失效或损坏数据；停止运动")
            finally:
                self._raw_context.append(self._current_raw)
                self._current_raw=None

    def poll_available(self):
        """行程模式拒绝超过4096字节的已知积压，其余非阻塞读取。"""
        old_timeout = self.ser.timeout
        try:
            self.ser.timeout = 0
            size = self.ser.in_waiting
            self.max_rx_waiting = max(self.max_rx_waiting, size)
            if size > 4096:
                self.note_failure('serial_backlog_limit')
                self.velocity_validity.failed = True
                self._invalidate_stop_observation()
                raise RuntimeError('串口待接收积压超过4096字节；禁止以重新接收时间继续运动')
            self._consume(self.ser.read(size) if size else b"")
        except OSError:
            self.note_failure("read_exception")
            raise
        finally:
            self.ser.timeout = old_timeout

    def _unknown(self, line):
        self.unknown_count += 1
        if self.velocity_validity.active or self.stop_observation is not None:
            kind=line.split()[:1]
            reason=('malformed_'+kind[0].lower()) if kind and kind[0] in ('STATE','MODE','EVENT','OK') else 'unknown_line'
            self.note_failure(reason,current_raw=True)
        if self.stop_observation is not None:
            self.velocity_validity.failed = True
            self._invalidate_stop_observation()
            raise RuntimeError('停车观测收到未知或损坏数据')
        if self.velocity_validity.active:
            self.velocity_validity.failed = True
            self.last_state = None
            self.state_received_at = None
            # 交由运动门禁中止；在零速请求前不得阻塞于stdout。
        else:
            self._output("[UNKNOWN] %r" % line)

    def _dispatch(self, line):
        if line.split()[:1] == ["EVENT"]:
            # 先限字段长度再转整数，拒绝符号、下划线和超长十进制串。
            match = re.fullmatch(r"EVENT STEP_LOSS ([0-9]{1,10}) ([0-9]{1,10}) ([0-9]{1,19})", line)
            if match is None:
                self._unknown(line)
                return
            event_id, run_id, device_us = map(int, match.groups())
            if not (0 < event_id <= 0xffffffff and 0 < run_id <= 0xffffffff
                    and device_us <= 0x7fffffffffffffff):
                self._unknown(line)
                return
            self.last_step_loss_event = dict(event_id=event_id, run_id=run_id,
                                            device_us=device_us, host_received_at=self._clock())
            self.event_count += 1  # 合法接收行数，重复也计；未验证与当前运行匹配。
            message = f"[EVENT STEP_LOSS {event_id} {run_id} {device_us}] 运行身份未核验"
            if self.step_loss_policy == "stop" and self.velocity_validity.active:
                self.note_failure('step_loss_stop_policy',current_raw=True)
                self.velocity_validity.failed = True
                # 调用方先请求零速，再显示带事件身份的异常。
                raise RuntimeError(message + "；按 stop 策略中止")
            self._output(message)
            return
        if line.split()[:1] == ['STATE']:
            try:frame=parse_state_frame(line)
            except ValueError:
                self._unknown(line);return
            self.on_measurement_frame(frame)
            gate=self.stop_observation or self.velocity_validity
            if self.stop_observation is None and self.velocity_validity.active:self.note_velocity_gate()
            try:fresh=gate.update(frame)
            except RuntimeError:
                self.note_failure('measurement_gate_error',current_raw=True)
                self.velocity_validity.failed=True
                self.clear_motion_state()
                raise
            if frame['flags']&gate.required_mask != gate.required_mask:
                self.note_failure('measurement_invalid',current_raw=True)
                self.clear_motion_state()
                if self.stop_observation is not None:raise RuntimeError('停车观测所需测量无效')
            if fresh:self.accept_measurement_frame(frame)
            elif gate.failed:self.clear_motion_state()
            return
        elif line.startswith("MODE "):
            parts = line.split()
            if len(parts) == 3:
                self.last_mode = (parts[1], parts[2])
                self._output("[MODE] %s %s" % self.last_mode)
                if self.velocity_validity.active and self.last_mode != ("READY","NONE"):
                    self.note_failure("firmware_mode_changed",current_raw=True)
                    self.velocity_validity.failed=True
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


from cart_motion import CartMotionMixin

class CartRig(CartMotionMixin, Rig):
    pass


def cmd_vel(rig, args):
    rig.timing = SessionTiming(getattr(rig, "_clock", time.monotonic))
    if args.hold is None:
        from travel_limit import run
        return run(rig, args)
    m = rig.query()
    if not m or m[0] != "READY":
        print("当前模式 %s，非 READY——先标定并 ENABLE" % (m,))
        return 1
    rig.timing.mark("preflight_complete")
    end = time.time() + args.hold
    n = 0
    while time.time() < end:
        rig.send_line("VEL %d" % args.v)
        n += 1
        rig.pump(0.005)
    rig.pump(0.3)
    print("已发送 %d 条 VEL（%.1f Hz）" % (n, n / args.hold))
    if isinstance(rig, CartMotionMixin):
        if rig.last_cart:
            x,vx=rig.motion_cart()
            print("最新独立小车测量：x=%.3f mm，vx=%d mm/s；非摆杆状态"%(x/1000,vx))
        return 0
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
    print("有效 STATE 行（dump 窗口内）：%d" % rig.state_count)
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
    print("时长 %.1f s，有效 STATE %d 行 → %.1f Hz" %
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
        print("未指定目标频率，仅检查收到有效 STATE 且 UNKNOWN 为 0；不证明期间没有无效帧。")
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


def latest_velocity_for_timing(rig):
    if isinstance(rig, CartMotionMixin):
        return rig.motion_cart()[1] if rig.state_is_fresh() else None
    """纯读取观测资格；不调用会改变运动失败锁存的ready。"""
    validity=rig.velocity_validity
    if (rig.last_state is None or not rig.state_is_fresh()
            or validity.flags != (1,1) or validity.age() is None
            or not 0 <= validity.age() <= .1):
        return None
    return int(rig.last_state[2])


def main():
    ap = argparse.ArgumentParser(description="cartpole 固件串口联调工具")
    ap.add_argument("--port", required=True, help="串口（如 COM7）")
    ap.add_argument("--baud", type=int, default=460800)
    ap.add_argument("--step-loss-policy", choices=("report", "stop"), default="report",
                    help="合法 STEP_LOSS 事件：report 仅报告（默认）；stop 中止活动会话并请求零速")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("query")
    sub.add_parser("calibrate-pole-down", help="自然下垂静止时校准摆杆零点，仅DISABLED")
    sub.add_parser("mark-left")
    sub.add_parser("mark-right")
    sub.add_parser("confirm-left")
    sub.add_parser("calib-status")
    p = sub.add_parser("enable"); p.add_argument("--timeout", type=float, default=5.0)
    p = sub.add_parser("vel"); p.add_argument("v", type=int)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--hold", type=float, default=None)
    p.add_argument("--reserve-mm", type=float, default=20)
    p.add_argument("--start-tolerance-mm", type=float, default=.5, help="起点读数容差0..1mm，仅允许向内")
    p.add_argument("--inflight-ms", type=float, default=10, help="调试延迟余量ms，默认10；非实测延迟上界")
    p.add_argument("--max-seconds", type=float, default=30)
    group.add_argument("--plan", action="store_true", help="只读单程规划，不发送运动命令")
    p = sub.add_parser("config"); p.add_argument("name"); p.add_argument("value", type=int)
    sub.add_parser("dump")
    p = sub.add_parser("state"); p.add_argument("--secs", type=float, default=10.0)
    p.add_argument("--expected-hz", type=float, help="预期 STATE 频率，容差 ±1 Hz；省略时仅报告实测频率")
    sub.add_parser("wdt-test")
    sub.add_parser("console")
    sub.add_parser("reset")
    sub.add_parser("disable")

    args = ap.parse_args()
    if args.cmd == "vel":
        if args.hold is None:
            if not math.isfinite(args.start_tolerance_mm) or not 0 <= args.start_tolerance_mm <= 1:
                ap.error("--start-tolerance-mm 必须为0..1mm有限数")
            if not args.v or not all(math.isfinite(v) and v >= 0 for v in
                    (args.reserve_mm, args.inflight_ms)) or not math.isfinite(args.max_seconds) or args.max_seconds <= 0:
                ap.error("行程速度须非零，余量/在途预算须非负有限，期限须正有限")
        elif not math.isfinite(args.hold) or args.hold <= 0:
            ap.error("--hold 必须是正的有限秒数")
    if args.cmd == "state":
        if not math.isfinite(args.secs) or args.secs <= 0:
            ap.error("--secs 必须是正的有限秒数")
        if args.expected_hz is not None and (
                not math.isfinite(args.expected_hz) or args.expected_hz <= 0):
            ap.error("--expected-hz 必须是正的有限频率")
    if args.cmd == "calibrate-pole-down":
        from pole_zero import calibrate_port
        try:
            sys.exit(calibrate_port(args.port, args.baud))
        except (RuntimeError, ValueError, OSError) as exc:
            print(f"标定中止：{exc}", file=sys.stderr)
            sys.exit(1)

    rig = (CartRig if args.cmd == "vel" else Rig)(args.port, args.baud, step_loss_policy=args.step_loss_policy)
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
    except (RuntimeError, ValueError, OSError, KeyboardInterrupt) as exc:
        if isinstance(getattr(rig, '_raw_context', None), deque):
            rig.note_failure('user_interrupt' if isinstance(exc,KeyboardInterrupt) else 'command_error_without_raw')
        stop_error = None
        if rig.velocity_validity.active:
            try:
                rig.send_line("VEL 0")
            except (OSError, RuntimeError) as error:
                stop_error = error
        print("命令中止：%s" % ("用户中断（Ctrl+C）" if isinstance(exc, KeyboardInterrupt) else exc))
        if stop_error is not None:
            print("零速请求失败：%s；请使用独立断电。" % stop_error)
        rc = 1
    finally:
        rig.close()
        if isinstance(rig, CartMotionMixin):
            try: print(rig.cart_diagnostic_summary())
            except Exception: pass
        if isinstance(getattr(rig, "first_failure", None), dict):
            try:
                diagnostic=rig.failure_summary()
                if diagnostic is not None:print(diagnostic)
            except Exception:
                pass  # 诊断输出失败不得覆盖原命令结果；清理已先完成。
        timing = getattr(rig, 'timing', None)
        if isinstance(timing, SessionTiming):
            try:
                timing.finish(latest_velocity=latest_velocity_for_timing(rig))
                print(timing.summary())
            except Exception:
                # 旁路统计不能覆盖命令结果；串口关闭及异常零速已先执行。
                pass
    sys.exit(rc)


if __name__ == "__main__":
    main()
