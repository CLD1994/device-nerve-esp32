#!/usr/bin/env python3
"""只读收集固件STEP_LOSS证据；不配置、使能或发送运动命令。"""
import argparse
import json
import re
import time
from pathlib import Path

FIELDS = frozenset("""VERSION RUN_COMPARE RUN_ACCEPT T_COMPARE_US T_ACCEPT_US
C_BEGIN_US C_END_US TIME_ORDER_OK E_SENSOR_UM E_COMPARED_UM C_UM ERROR_UM
THRESHOLD_UM TARGET_ACCEPT_MM_S META_AVAILABLE ENC_V_MM_S ENC_V_VALID ENC_SPAN_US
SAMPLE_US AGE_US SAMPLE_SEQ FAILURE_SEQ CONTINUITY_SEQ GAP_US SAMPLE_VALID
LAST_READ_OK""".split())
SL = re.compile(r"SL1 ([0-9]+) ([A-Z_]+) (-?[0-9]+)")
BACKGROUND = re.compile(r"(?:STATE -?[0-9]+ -?[0-9]+ -?[0-9]+ -?[0-9]+|VEL_VALID [01] [01]|MODE [A-Z_]+ [A-Z_]+)")

class Capture:
    def __init__(self):
        self.event_id = None
        self.fields = {}
        self.done = False

    def feed(self, line):
        if line.startswith("ERR "):
            raise ValueError(f"固件拒绝诊断：{line}")
        if BACKGROUND.fullmatch(line):
            return None
        match = SL.fullmatch(line)
        if not match:
            raise ValueError(f"无法解析完整串口行：{line!r}")
        if self.done:
            raise ValueError("结束标记后收到重复诊断")
        event, name, value = int(match[1]), match[2], int(match[3])
        if self.event_id is None:
            self.event_id = event
        if event != self.event_id:
            raise ValueError("诊断event_id改变，不拼接不同事件")
        if name == "END":
            if value != 1 or self.fields.keys() != FIELDS or self.fields.get("VERSION") != 1:
                raise ValueError("证据字段缺失、版本不支持或结束标记无效")
            self.done = True
            return {"event_id": self.event_id, **self.fields}
        if name not in FIELDS or name in self.fields:
            raise ValueError(f"未知或重复证据字段：{name}")
        self.fields[name] = value
        return None

def collect(ser, timeout=3.0):
    # 开串口时可能正处于STATE中间；只丢弃第一条边界残行，之后严格解析。
    ser.read_until(b"\n")
    request = b"STEPLOSS?\n"
    if ser.write(request) != len(request):
        raise ValueError("诊断请求未完整写入串口，不接收不确定应答")
    # 不调用flush：驱动排空可能不受write_timeout约束。这里的接收期限从写入返回后算。
    deadline = time.monotonic() + timeout
    capture = Capture()
    pending = bytearray()
    while time.monotonic() < deadline:
        pending.extend(ser.read(ser.in_waiting or 1))
        if len(pending) > 16384:
            raise ValueError("串口行/缓冲超限")
        while b"\n" in pending:
            line, _, tail = pending.partition(b"\n")
            pending = bytearray(tail)
            result = capture.feed(line.decode("ascii").rstrip("\r"))
            if result is not None:
                return result
    raise TimeoutError("未收到完整STEP_LOSS证据，不保存部分结果")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=460800)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("输出文件已存在，请使用新文件名")
    import serial
    try:
        with serial.Serial(args.port, args.baud, timeout=0.2, write_timeout=1) as ser:
            record = collect(ser)
    except (ValueError, TimeoutError, serial.SerialException) as error:
        raise SystemExit(str(error)) from error
    with args.out.open("x", encoding="utf-8") as target:
        json.dump(record, target, ensure_ascii=False, indent=2)
        target.write("\n")
    print(f"已保存事件 {record['event_id']} 的只读证据：{args.out}")
    print("E与C不是同时采样；C是软件STEP位置，不证明物理脉冲或失步。")

if __name__ == "__main__":
    main()
