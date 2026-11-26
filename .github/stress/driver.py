"""Run child.py in fresh processes until the time budget ends. Dump hung children."""

from __future__ import annotations

import argparse
import ctypes
import glob
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
CASES = (
    "test_cross_module_gil_acquired",
    "test_cross_module_gil_acquired",
    "test_cross_module_gil_acquired",
    "test_cross_module_gil_released",
)
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

parser = argparse.ArgumentParser()
parser.add_argument("--tests-dir", required=True)
parser.add_argument("--minutes", type=float, default=20)
parser.add_argument("--jobs", type=int, default=6)
parser.add_argument("--timeout", type=float, default=25)
parser.add_argument("--max-hangs", type=int, default=5)
parser.add_argument("--out", default="stress-out")
parser.add_argument("--pdb-dir", default="")
args = parser.parse_args()

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
deadline = time.monotonic() + 60 * args.minutes
lock = threading.Lock()
counts = {"runs": 0, "hangs": 0, "errors": 0}


def find_cdb():
    hits = glob.glob(r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe")
    return hits[0] if hits else None


def minidump(proc, path):
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
            int(proc._handle),
            proc.pid,
            msvcrt.get_osfhandle(f.fileno()),
            0x2 | 0x4 | 0x1000,
            None,
            None,
            None,
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


def report_hang(proc, case, stdout_path, stderr_path):
    with lock:
        counts["hangs"] += 1
        index = counts["hangs"]
        lines = [f"===== HANG {index}: {case} pid={proc.pid} after run {counts['runs']}"]
        lines.append("--- child stdout\n" + stdout_path.read_text(errors="replace"))
        lines.append("--- child stderr\n" + stderr_path.read_text(errors="replace"))
        if sys.platform == "win32":
            if index <= 3:
                try:
                    lines.append(minidump(proc, out / f"hang-{index}.dmp"))
                except Exception as error:
                    lines.append(f"minidump failed: {error!r}")
            lines.append("--- native stacks\n" + native_stacks(proc.pid))
        text = "\n".join(lines)
        (out / f"hang-{index}.txt").write_text(text, errors="replace")
        print(text, flush=True)


def worker(number):
    stdout_path = out / f"worker-{number}.stdout"
    stderr_path = out / f"worker-{number}.stderr"
    iteration = number
    while time.monotonic() < deadline and counts["hangs"] < args.max_hangs:
        case = CASES[iteration % len(CASES)]
        iteration += 1
        with open(stdout_path, "wb") as so, open(stderr_path, "wb") as se:
            proc = subprocess.Popen(
                [sys.executable, str(HERE / "child.py"), args.tests_dir, case],
                stdout=so,
                stderr=se,
            )
            try:
                code = proc.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                report_hang(proc, case, stdout_path, stderr_path)
                proc.kill()
                proc.wait()
                continue
        with lock:
            counts["runs"] += 1
            if code != 0:
                counts["errors"] += 1
                if counts["errors"] <= 5:
                    print(
                        f"===== ERROR exit {code}: {case}\n"
                        + stdout_path.read_text(errors="replace")
                        + stderr_path.read_text(errors="replace"),
                        flush=True,
                    )
            if counts["runs"] % 500 == 0:
                print(f"progress {counts}", flush=True)


print(f"python {sys.version}\ncdb {find_cdb()}\ntests {args.tests_dir}", flush=True)
threads = [threading.Thread(target=worker, args=(n,)) for n in range(args.jobs)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print(f"RESULT {counts}", flush=True)
