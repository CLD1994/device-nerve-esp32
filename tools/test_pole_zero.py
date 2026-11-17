import unittest
from unittest.mock import patch
import cartpole_host
from collections import deque
from pole_zero import CalibrationSession, estimate_zero, wrap, PI


class Serial:
    def __init__(self, inv=0):
        self.t = 0.0
        self.queue = deque()
        self.zero, self.inv = 123456, inv
        self.writes = []
        self.theta = PI
        self.flags, self.speed = 3, 0
        self.mode = 'DISABLED'
        self.config_reads = 0
        self.change_before_write = False
        self.bad_readback = False
        self.drop = False
        self.reset_count = 0

    def clock(self):
        return self.t

    def reset_input_buffer(self):
        self.reset_count += 1
        self.queue.clear()

    def write(self, data):
        command = data.decode().strip()
        self.writes.append(command)
        if command == 'QUERY':
            self.queue.append(f'MODE {self.mode} NONE\n'.encode())
        elif command == 'CONFIG?':
            self.config_reads += 1
            if self.change_before_write and self.config_reads == 2:
                self.inv = 1 - self.inv
            zero = self.zero + (1 if self.bad_readback and self.config_reads == 3 else 0)
            self.queue.extend([f'OK POLE_ZERO_URAD {zero}\n'.encode(), f'OK POLE_INV {self.inv}\n'.encode()])
        else:
            self.zero = int(command.split()[-1])
            self.queue.append(f'OK POLE_ZERO_URAD {self.zero}\n'.encode())
        return len(data)

    def read_until(self, delimiter, size):
        self.t += .002
        if self.drop:
            self.t += .1
            return b''
        if self.queue:
            return self.queue.popleft()
        theta = self.theta if self.flags & 2 else 0
        return f'STATE {self.flags} 0 {theta} 0 {self.speed if self.flags & 2 else 0}\n'.encode()


class PoleZeroTest(unittest.TestCase):
    def test_both_directions_and_wrap(self):
        for inv in (0, 1):
            for old in (-PI, -123456, 0, PI):
                for theta in (-PI, -2000000, 0, 2000000, PI):
                    new = estimate_zero([theta] * 5, old, inv)
                    raw = old + (-theta if inv else theta)
                    actual = (-1 if inv else 1) * wrap(raw - new)
                    self.assertLessEqual(abs(wrap(actual - PI)), 1)
                    self.assertTrue(-PI <= new <= PI)

    def test_seam_statistics(self):
        self.assertLessEqual(abs(wrap(estimate_zero([PI, -PI] * 100, 0, 0))), 1)

    def test_unstable(self):
        with self.assertRaises(ValueError):
            estimate_zero([0, 20000], 0, 0)

    def test_success_preserves_inv_no_motion(self):
        for inv in (0, 1):
            link = Serial(inv)
            old, new = CalibrationSession(link, link.clock).calibrate()
            self.assertEqual(new['POLE_INV'], inv)
            self.assertEqual(link.reset_count, 1)
            writes = [x for x in link.writes if x.startswith('CONFIG ')]
            self.assertEqual(writes, [f"CONFIG POLE_ZERO_URAD {new['POLE_ZERO_URAD']}"])
            self.assertEqual(old['POLE_ZERO_URAD'], 123456)

    def refuse(self, link):
        with self.assertRaises((ValueError, RuntimeError)):
            CalibrationSession(link, link.clock).calibrate()
        self.assertFalse(any(x.startswith('CONFIG ') for x in link.writes))

    def test_non_disabled(self):
        link = Serial();link.mode = 'READY';self.refuse(link)

    def test_invalid(self):
        link = Serial();link.flags = 1;self.refuse(link)

    def test_moving(self):
        link = Serial();link.speed = 21;self.refuse(link)

    def test_changed_config(self):
        link = Serial();link.change_before_write = True;self.refuse(link)

    def test_disconnected(self):
        link = Serial();link.drop = True;self.refuse(link)

    def test_readback_failure_no_rollback(self):
        link = Serial();link.bad_readback = True
        with self.assertRaisesRegex(RuntimeError, '读回不一致'):
            CalibrationSession(link, link.clock).calibrate()
        self.assertEqual(len([x for x in link.writes if x.startswith('CONFIG ')]), 1)

    def test_old_host_cache_discarded(self):
        link = Serial();link.queue.append(b'MODE READY NONE\n')
        CalibrationSession(link, link.clock).calibrate()

    def test_invalid_frame_inside_window(self):
        link = Serial()
        read = link.read_until
        def intermittent(*args, **kwargs):
            if .4 < link.t < .41:
                link.flags = 1
            return read(*args, **kwargs)
        link.read_until = intermittent
        self.refuse(link)

    def test_unstable_window(self):
        link = Serial()
        read = link.read_until
        def swinging(*args, **kwargs):
            link.theta = 100000 if link.t > .5 else 0
            return read(*args, **kwargs)
        link.read_until = swinging
        self.refuse(link)

    def test_insufficient_rate(self):
        link = Serial()
        read = link.read_until
        def slow(*args, **kwargs):
            link.t += .01
            return read(*args, **kwargs)
        link.read_until = slow
        self.refuse(link)

    def test_mode_changed_after_sampling(self):
        link = Serial()
        write = link.write
        def change(data):
            if data == b'QUERY\n' and link.config_reads == 2:
                link.mode = 'READY'
            return write(data)
        link.write = change
        self.refuse(link)

    def test_cli_exit_codes(self):
        argv = ['cartpole_host.py', '--port', 'memory', 'calibrate-pole-down']
        with patch('sys.argv', argv), patch('pole_zero.calibrate_port', return_value=0):
            with self.assertRaises(SystemExit) as caught:
                cartpole_host.main()
            self.assertEqual(caught.exception.code, 0)
        with patch('sys.argv', argv), patch('pole_zero.calibrate_port', side_effect=RuntimeError('offline')):
            with self.assertRaises(SystemExit) as caught:
                cartpole_host.main()
            self.assertEqual(caught.exception.code, 1)

    def test_short_write(self):
        link = Serial();link.write = lambda _: 0;self.refuse(link)


if __name__ == '__main__':
    unittest.main()
