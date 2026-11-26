"""Run the real test_gil_scoped subprocess harness in a loop beside CPU load."""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--tests-dir", required=True)
parser.add_argument("--source-tests", required=True)
parser.add_argument("--minutes", type=float, default=10)
parser.add_argument("--jobs", type=int, default=1)
parser.add_argument("--load", type=int, default=0)
parser.add_argument("--harness-timeout", type=float, default=0, help="0 = test default")
parser.add_argument("--worker", type=int, default=None)
args = parser.parse_args()


def run_worker():
    sys.path[:0] = [args.tests_dir, args.source_tests]
    import test_gil_scoped as t

    if args.harness_timeout:
        t._run_in_process.__kwdefaults__["timeout"] = args.harness_timeout
    print(f"worker {args.worker}: timeout={t._run_in_process.__kwdefaults__}", flush=True)
    cases = [getattr(c, "values", (c,))[0] for c in t.PROCESS_TEST_CASES]
    deadline = time.monotonic() + 60 * args.minutes
    durations = []
    deadlocks = errors = 0
    index = 0
    while time.monotonic() < deadline:
        fns = cases[index % len(cases)]
        index += 1
        start = time.monotonic()
        try:
            t._run_test_cases_in_process(fns, num_threads=8, parallel=False)
        except BaseException as error:
            if "DEADLOCK" in str(error):
                deadlocks += 1
                if deadlocks <= 2:
                    print(f"===== DEADLOCK worker={args.worker}\n{error}", flush=True)
            else:
                errors += 1
                print(f"===== ERROR worker={args.worker} {error!r}", flush=True)
        durations.append(time.monotonic() - start)
    durations.sort()
    print(
        f"RESULT worker={args.worker} runs={len(durations)} deadlocks={deadlocks} "
        f"errors={errors} median={statistics.median(durations):.2f}s "
        f"p99={durations[int(0.99 * (len(durations) - 1))]:.2f}s max={durations[-1]:.2f}s",
        flush=True,
    )


if __name__ == "__main__":
    if args.worker is not None:
        run_worker()
    else:
        print(f"python {sys.version}", flush=True)
        procs = [
            subprocess.Popen([sys.executable, __file__, *sys.argv[1:], "--worker", str(n)])
            for n in range(args.jobs)
        ]
        load = [
            subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(args.load)
        ]
        for proc in procs:
            proc.wait()
        for proc in load:
            proc.kill()
