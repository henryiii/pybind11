"""Latency of a blocking lock acquire and of Thread.start() beside CPU-bound processes.

Standard library only. Usage: python repro.py --load 4 --seconds 60
"""

from __future__ import annotations

import _thread
import argparse
import os
import subprocess
import sys
import threading
import time

parser = argparse.ArgumentParser()
parser.add_argument("--load", type=int, default=0, help="number of busy processes")
parser.add_argument("--seconds", type=float, default=60)
args = parser.parse_args()


def lock_handoff():
    # The main thread blocks on a held lock; a new thread releases it at once.
    lock = _thread.allocate_lock()
    lock.acquire()
    _thread.start_new_thread(lock.release, ())
    start = time.perf_counter()
    lock.acquire()
    return time.perf_counter() - start


def thread_start():
    thread = threading.Thread(target=lambda: None)
    start = time.perf_counter()
    thread.start()
    elapsed = time.perf_counter() - start
    thread.join()
    return elapsed


def measure(name, fn):
    samples = []
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        samples.append(fn())
    samples.sort()
    n = len(samples)
    print(
        f"{name:13} n={n:<8} median={samples[n // 2] * 1e3:9.3f} ms "
        f"p99={samples[int(0.99 * (n - 1))] * 1e3:9.3f} ms max={samples[-1] * 1e3:9.3f} ms "
        f">100ms={sum(s > 0.1 for s in samples)}",
        flush=True,
    )


if __name__ == "__main__":
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    print(f"python {sys.version}", flush=True)
    print(f"platform={sys.platform} cpus={os.cpu_count()} gil_enabled={gil} load={args.load}", flush=True)
    load = [
        subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(args.load)
    ]
    try:
        time.sleep(1)
        measure("lock handoff", lock_handoff)
        measure("Thread.start", thread_start)
    finally:
        for proc in load:
            proc.kill()
