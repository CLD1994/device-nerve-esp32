"""Disabled-only TMC register query. Sends only TMC?, never configuration/motion."""
import argparse
import json
import time

NAMES = {"GCONF", "CHOPCONF", "IFCNT", "IOIN", "DRV_STATUS"}

def collect(ser):
    # Discard one boundary fragment from the continuous STATE stream.
    ser.read_until(b"\n")
    request = b"TMC?\n"
    if ser.write(request) != len(request):
        raise ValueError("TMC request short write")
    end = time.monotonic() + 5
    rows = {}
    pending = bytearray()
    while time.monotonic() < end:
        pending.extend(ser.read(ser.in_waiting or 1))
        while b"\n" in pending:
            line, _, rest = pending.partition(b"\n")
            pending = bytearray(rest)
            if line.startswith(b"ERR "):
                raise ValueError(line.decode("ascii", errors="replace"))
            if not line.startswith(b"TMC1 "):
                continue
            words = line.decode("ascii").split()
            if words == ["TMC1", "END"]:
                if set(rows) != NAMES:
                    raise ValueError("incomplete TMC response")
                return rows
            if len(words) != 6 or words[1] not in NAMES or words[1] in rows:
                raise ValueError("malformed TMC response")
            valid, raw, start, stop = map(int, words[2:])
            if valid not in (0, 1) or not 0 <= raw <= 0xffffffff:
                raise ValueError("invalid TMC value")
            rows[words[1]] = dict(valid=bool(valid), raw=raw if valid else None,
                                  t_begin_us=start, t_end_us=stop)
    raise ValueError("TMC response timeout")

def main():
    import serial
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=460800)
    args = ap.parse_args()
    with serial.Serial(args.port, args.baud, timeout=0.2, write_timeout=1) as ser:
        rows = collect(ser)
    print(json.dumps(rows, indent=2))
    print("当前静止读数，不是故障瞬间；IHOLD_IRUN只写不可读。IFCNT不是电流值证明。")
    return 0 if all(r["valid"] for r in rows.values()) else 1

if __name__ == "__main__":
    raise SystemExit(main())
