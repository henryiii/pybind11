"""Run the real test_gil_scoped subprocess harness in a loop. Dump hung children."""

from __future__ import annotations

import argparse
import ctypes
import glob
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--tests-dir", required=True)
parser.add_argument("--source-tests", required=True)
parser.add_argument("--minutes", type=float, default=20)
parser.add_argument("--jobs", type=int, default=6)
parser.add_argument("--timeout", type=float, default=25)
parser.add_argument("--max-hangs", type=int, default=3)
parser.add_argument("--out", default="stress-out")
parser.add_argument("--pdb-dir", default="")
parser.add_argument("--worker", type=int, default=None)
parser.add_argument("--fresh-copy", type=int, default=0)
parser.add_argument("--load", type=int, default=0)
args = parser.parse_args()

PYDLL = f"python{sys.version_info.major}{sys.version_info.minor}t"
CDB_COMMANDS = "; ".join(
    [
        ".lines -e",
        "~*kn 60",
        f"dx -r1 {PYDLL}!_PyRuntime._main_interpreter._gil",
        f"dx -r1 {PYDLL}!_PyRuntime.stoptheworld",
        f"dx -r1 {PYDLL}!_PyRuntime._main_interpreter.stoptheworld",
        f"dx -r1 *{PYDLL}!_PyRuntime._main_interpreter.threads.head",
        f"dx -r1 {PYDLL}!_PyRuntime._main_interpreter._initial_thread",
        "qd",
    ]
)


def find_cdb():
    hits = glob.glob(r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe")
    return hits[0] if hits else None


def minidump(handle, pid, path):
    import msvcrt
    from ctypes import wintypes

    write = ctypes.WinDLL("dbghelp", use_last_error=True).MiniDumpWriteDump
    write.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    write.restype = wintypes.BOOL
    with open(path, "wb") as f:
        # FullMemory | HandleData | ThreadInfo
        ok = write(
            handle, pid, msvcrt.get_osfhandle(f.fileno()), 0x2 | 0x4 | 0x1000, None, None, None
        )
    return f"minidump ok={ok} err={ctypes.get_last_error()} size={os.path.getsize(path)}"


def native_stacks(pid):
    cdb = find_cdb()
    if cdb is None:
        return "cdb not found"
    sympath = r"srv*C:\sym*https://msdl.microsoft.com/download/symbols"
    if args.pdb_dir:
        sympath = f"{args.pdb_dir};{sympath}"
    try:
        result = subprocess.run(
            [cdb, "-pv", "-p", str(pid), "-y", sympath, "-c", CDB_COMMANDS],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return f"cdb timeout: {error.stdout!r}"
    return result.stdout + result.stderr


def drain(reader):
    items = []
    try:
        while reader.poll():
            items.append(reader.recv())
    except (EOFError, OSError):
        pass
    return items


def run_worker():
    # Slot 0 is replaced per run when --fresh-copy is set.
    sys.path[:0] = [args.tests_dir, args.tests_dir, args.source_tests]
    import test_gil_scoped as t

    cross_files = glob.glob(os.path.join(args.tests_dir, "cross_module_gil_utils*.*"))
    cross_files = [f for f in cross_files if f.endswith((".pyd", ".so"))]

    cases = (
        ("acquired", (t.test_cross_module_gil_acquired,), False),
        ("acquired", (t.test_cross_module_gil_acquired,), False),
        ("released", (t.test_cross_module_gil_released,), False),
        ("acquired", (t.test_cross_module_gil_acquired,), False),
        ("all_basic", t.ALL_BASIC_TESTS, False),
        ("acquired_parallel", (t.test_cross_module_gil_acquired,), True),
    )
    out = Path(args.out) / f"w{args.worker}"
    out.mkdir(parents=True, exist_ok=True)
    traceback_path = str(out / "tracebacks.txt")
    deadline = time.monotonic() + 60 * args.minutes
    runs = hangs = errors = 0
    iteration = args.worker
    while time.monotonic() < deadline and hangs < args.max_hangs:
        name, test_fns, parallel = cases[iteration % len(cases)]
        iteration += 1
        fresh = None
        if args.fresh_copy:
            # A new file path makes the first load in the worker thread cold
            # (file cache, antivirus scan), as in a single CI run.
            fresh = out / f"fresh-{iteration}"
            fresh.mkdir()
            for path in cross_files:
                shutil.copy(path, fresh)
            sys.path[0] = str(fresh)
        status_reader, status_writer = multiprocessing.Pipe(duplex=False)
        progress_reader, progress_writer = multiprocessing.Pipe(duplex=False)
        with status_reader, status_writer, progress_reader, progress_writer:
            process = multiprocessing.Process(
                target=t._run_in_process_target,
                args=(
                    t._run_test_cases,
                    (test_fns, progress_writer, 8, parallel),
                    {},
                    status_writer,
                    traceback_path,
                    10,
                ),
            )
            process.daemon = True
            process.start()
            process.join(args.timeout)
            if process.exitcode is None:
                hangs += 1
                lines = [
                    f"===== HANG worker={args.worker} n={hangs} case={name} "
                    f"pid={process.pid} after {runs} runs",
                    f"status={drain(status_reader)} progress={drain(progress_reader)}",
                ]
                try:
                    dump = Path(traceback_path).read_text(errors="replace")
                except OSError as error:
                    dump = repr(error)
                lines.append("--- faulthandler\n" + dump)
                if sys.platform == "win32":
                    try:
                        handle = int(process._popen._handle)
                        lines.append(minidump(handle, process.pid, out / f"hang-{hangs}.dmp"))
                    except Exception as error:
                        lines.append(f"minidump failed: {error!r}")
                    lines.append("--- native stacks\n" + native_stacks(process.pid))
                text = "\n".join(lines)
                (out / f"hang-{hangs}.txt").write_text(text, errors="replace")
                print(text, flush=True)
                process.terminate()
                process.join()
                continue
            if fresh is not None:
                shutil.rmtree(fresh, ignore_errors=True)
            runs += 1
            if process.exitcode != 0:
                errors += 1
                if errors <= 3:
                    print(
                        f"===== ERROR worker={args.worker} case={name} exit={process.exitcode}",
                        flush=True,
                    )
            if runs % 200 == 0:
                print(f"worker {args.worker}: runs={runs} hangs={hangs} errors={errors}", flush=True)
    print(f"RESULT worker={args.worker} runs={runs} hangs={hangs} errors={errors}", flush=True)


if __name__ == "__main__":
    if args.worker is not None:
        run_worker()
    else:
        print(f"python {sys.version}\ncdb {find_cdb()}", flush=True)
        # One process per worker: a hang in a driver cannot block the others.
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
