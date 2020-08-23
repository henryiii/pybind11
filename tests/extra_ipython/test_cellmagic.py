# -*- coding: utf-8 -*-
import sys
from textwrap import dedent
from IPython.testing.globalipapp import get_ipython


ip = get_ipython()
ip.magic("load_ext pybind11")


def test_compile(tmpdir):
    ip.run_cell_magic(
        "pybind11",
        "--force --path {}".format(tmpdir),
        dedent(
            """\
            int f(int x) {
                return x*2;
            }

            PYBIND11_MODULE(test_cellmagic_test_compile, m) {
                m.def("f", &f);
            }
            """
        ),
    )
    assert sys.modules["test_cellmagic_test_compile"].f(2) == 4
    items = tmpdir.listdir(lambda f: not f.check(dir=True))
    print(*items, sep="\n")
    assert len(items) == 3  # cpp, txt, and shared object
