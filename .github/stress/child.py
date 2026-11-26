"""One child run: 8 sequential threads call a pybind11_tests.gil_scoped function."""

import faulthandler
import os
import sys
import threading

sys.path.insert(0, sys.argv[1])
from pybind11_tests import gil_scoped as m  # noqa: E402

fn = getattr(m, sys.argv[2])
faulthandler.dump_traceback_later(9, repeat=True, file=sys.stderr)


def run_test():
    fn()


for i in range(8):
    # Unbuffered progress: worker index and GIL state before each start.
    os.write(1, b"start %d gil=%d\n" % (i, sys._is_gil_enabled()))
    thread = threading.Thread(target=run_test)
    thread.daemon = True
    thread.start()
    thread.join()
os.write(1, b"done\n")
