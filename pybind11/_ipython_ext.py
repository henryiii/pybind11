# -*- coding: utf-8 -*-

"""
This file provides the pybind11 magic for ipython / jupyter.

Use with %load_ext pybind11

Inspired heavily by %load_ext juptyer.
"""

import io
import re
import imp
import time
import sys
import os
import hashlib

try:
    from setuptools import Distribution
except ImportError:
    print("%%pybind11: no setuptools, using distutils")
    from distutils.core import Distribution
import distutils.errors

from IPython.core import magic_arguments
from IPython.core.magic import Magics, magics_class, cell_magic

try:
    from IPython.paths import get_ipython_cache_dir
except ImportError:
    # older IPython version
    from IPython.utils.path import get_ipython_cache_dir
from IPython.utils.text import dedent

from . import __version__ as pybind11_version
from .setup_helpers import Pybind11Extension, build_ext

# Based on https://github.com/cython/cython/blob/master/Cython/Build/IpythonMagic.py,
# which itself was taken from IPython.
#
# -----------------------------------------------------------------------------
# Copyright (C) 2010-2011, IPython Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file ipython-COPYING.rst, distributed with this software.
# -----------------------------------------------------------------------------


PYBIND11_MODULE_RE = re.compile(
    r"""
            PYBIND11_MODULE # macro
            \s*             # optional whitespace
            \(              # opening (
            \s*             # optional whitespace
            (\w+)           # capture alphanumeric name
            \s*             # optional whitespace
            ,               # ending comma
            """,
    re.DOTALL | re.VERBOSE,
)

IO_ENCODING = sys.getfilesystemencoding()


def encode_fs(name):
    if sys.version_info[0] < 3:
        return name if isinstance(name, bytes) else name.encode(IO_ENCODING)
    else:
        return name


@magics_class
class Pybind11Magics(Magics):
    def __init__(self, shell):
        super(Pybind11Magics, self).__init__(shell)
        self._reloads = {}

    def _import_module(self, name, module):
        self.shell.push({name: module})

    def _import_all(self, module):
        mdict = module.__dict__
        if "__all__" in mdict:
            keys = mdict["__all__"]
        else:
            keys = [k for k in mdict if not k.startswith("_")]

        for k in keys:
            try:
                self.shell.push({k: mdict[k]})
            except KeyError:
                msg = "'module' object has no attribute '%s'" % k
                raise AttributeError(msg)

    @magic_arguments.magic_arguments()
    @magic_arguments.argument(
        "-s",
        "--std",
        dest="cxx_std",
        type=int,
        help="Select a C++ standard to use, defaults to highest supported (17, 14, then 11).",
    )
    @magic_arguments.argument(
        "-r",
        "--raw",
        action="store_true",
        help="Do not add any helper includes or namespaces.",
    )
    @magic_arguments.argument(
        "--all",
        dest="all",
        action="store_true",
        help="run import * on the module",
    )
    @magic_arguments.argument(
        "--path",
        dest="path",
        help="Directory to build the extension in (defaults to ipython dir)",
    )
    @magic_arguments.argument(
        "-f",
        "--force",
        action="store_true",
        help="Force the compilation of a new module, even if the source has been "
        "previously compiled.",
    )
    @magic_arguments.argument(
        "-c",
        "--compile-args",
        action="append",
        default=[],
        help="Extra flags to pass to compiler via the `extra_compile_args` "
        "Extension flag (can be specified  multiple times).",
    )
    @magic_arguments.argument(
        "--link-args",
        action="append",
        default=[],
        help="Extra flags to pass to linker via the `extra_link_args` "
        "Extension flag (can be specified  multiple times).",
    )
    @magic_arguments.argument(
        "-l",
        "--lib",
        action="append",
        default=[],
        help="Add a library to link the extension against (can be specified "
        "multiple times).",
    )
    @magic_arguments.argument(
        "-n", "--name", help="Specify a name for the pybind11 module."
    )
    @magic_arguments.argument(
        "-L",
        dest="library_dirs",
        metavar="dir",
        action="append",
        default=[],
        help="Add a path to the list of library directories (can be specified "
        "multiple times).",
    )
    @magic_arguments.argument(
        "-I",
        "--include",
        action="append",
        default=[],
        help="Add a path to the list of include directories (can be specified "
        "multiple times).",
    )
    @magic_arguments.argument(
        "-S",
        "--src",
        action="append",
        default=[],
        help="Add a path to the list of src files (can be specified "
        "multiple times).",
    )
    @magic_arguments.argument(
        "--verbose",
        action="store_true",
        help="Print debug information like the command invoked.",
    )
    @magic_arguments.argument(
        "--quiet",
        action="store_true",
        help="Hide feedback.",
    )
    @cell_magic
    def pybind11(self, line, cell):
        """Compile and import everything from a pybind11 C++ code cell.

        The contents of the cell are written to a ``.cpp`` file in the
        directory ``IPYTHONDIR/pybind11`` using a filename with the hash of the
        code. This file is then compiled. If you do not supply a name, the
        name is collected from your ``PYBIND11_MODULE`` call and the resulting module
        is imported ::

            %%pybind11

            double f(double x) {
                return 2.0*x
            }

            PYBIND11_MODULE(myf, m) {
                m.def("f", f);
            }

        By default, a common set of imports and definitions is made for you; you
        can disable this with ``--raw``::

            %%pybind11 --raw

            #import <pybind11/pybind11.h>

            namespace py = pybind11;
            using namespace pybind11::literals;

            // then same code as above

        If you want the contents of the module imported (similar to ``from
        mymod import *``), you can add ``--all``. The highest standard
        supported is used by default, use ``--std=11`` to set an explicit
        standard. Use ``%%pybind11?`` to see other options.

        """

        args = magic_arguments.parse_argstring(self.pybind11, line)
        code = str(cell if cell.endswith("\n") else cell + "\n")

        key = (code, line, sys.version_info, sys.executable, pybind11_version)

        if args.force:
            # Force a new module name by adding the current time to the
            # key which is hashed to determine the module name.
            key += (time.time(),)

        if args.name:
            module_name = str(args.name)  # no-op in Py3
        else:
            match = PYBIND11_MODULE_RE.search(code)
            if not match:
                raise RuntimeError("Cannot find PYBIND22_MODULE(name, m)")
            module_name = str(match.group(1))

        if not args.raw:
            code = (
                dedent(
                    """\
            #include <pybind11/numpy.h>
            #include <pybind11/operators.h>
            #include <pybind11/pybind11.h>
            #include <pybind11/stl.h>

            namespace py = pybind11;
            using namespace pybind11::literals;
            """
                )
                + code
            )

        if not args.path:
            lib_dir = os.path.join(get_ipython_cache_dir(), "pybind11")
            if not os.path.exists(lib_dir):
                os.mkdir(lib_dir)
        else:
            lib_dir = os.path.abspath(os.path.expanduser(args.path))

        module_path = os.path.join(lib_dir, module_name + self.so_ext)
        last_compile = os.path.join(lib_dir, module_name + "._pybind11_magic_.txt")
        compile_sig = hashlib.sha1(str(key).encode("utf-8")).hexdigest()

        # See if this compile already happened
        try:
            with open(last_compile, "r") as f:
                matching_compile = compile_sig == f.read()
        except IOError:
            matching_compile = False

        have_module = os.path.isfile(module_path)

        if args.force or not have_module or not matching_compile:
            if not args.quiet:
                print("%%pybind11: building extension", module_name)
            extension = self._make_extension(module_name, code, lib_dir, args)

            try:
                self._build_extension(
                    extension, lib_dir, verbose=args.verbose, cxx_std=args.cxx_std
                )
            except distutils.errors.CompileError:
                # Build failed and printed error message
                return None

            with open(last_compile, "w") as f:
                f.write(compile_sig)

        if not args.quiet:
            print("%%pybind11: Loading extension", module_path)

        module = imp.load_dynamic(module_name, module_path)

        self._import_module(module_name, module)

        if args.all:
            self._import_all(module)

    def _build_extension(
        self, extension, lib_dir, temp_dir=None, verbose=False, cxx_std=None
    ):
        build_extension = self._get_build_extension(
            extension, lib_dir=lib_dir, temp_dir=temp_dir, cxx_std=None
        )
        old_threshold = None
        try:
            if verbose:
                old_threshold = distutils.log.set_threshold(distutils.log.DEBUG)
            build_extension.run()
        finally:
            if verbose and old_threshold is not None:
                distutils.log.set_threshold(old_threshold)

    def _make_extension(self, module_name, code, lib_dir, args):
        cpp_file = os.path.join(lib_dir, module_name + ".cpp")
        cpp_file = encode_fs(cpp_file)

        include_dirs = args.include
        src_files = list(map(str, args.src))

        with io.open(cpp_file, "w", encoding="utf-8") as f:
            f.write(code)

        ext = Pybind11Extension(
            name=module_name,
            sources=[cpp_file] + src_files,
            include_dirs=include_dirs,
            library_dirs=args.library_dirs,
            extra_compile_args=args.compile_args,
            extra_link_args=args.link_args,
            libraries=args.lib,
            language="c++",
        )
        ext._links_to_dynamic = False
        ext._needs_stub = False
        return ext

    @property
    def so_ext(self):
        """The extension suffix for compiled modules."""
        try:
            return self._so_ext
        except AttributeError:
            self._so_ext = self._get_build_extension().get_ext_filename("")
            return self._so_ext

    def _clear_distutils_mkpath_cache(self):
        """clear distutils mkpath cache
        prevents distutils from skipping re-creation of dirs that have been removed
        """
        try:
            from distutils.dir_util import _path_created
        except ImportError:
            pass
        else:
            _path_created.clear()

    def _get_build_extension(
        self, extension=None, lib_dir=None, temp_dir=None, cxx_std=None
    ):
        self._clear_distutils_mkpath_cache()
        dist = Distribution()
        config_files = dist.find_config_files()
        try:
            config_files.remove("setup.cfg")
        except ValueError:
            pass
        dist.parse_config_files(config_files)

        if not temp_dir:
            temp_dir = lib_dir

        build_extension = build_ext(dist)
        build_extension.cxx_std = cxx_std
        build_extension.finalize_options()
        if temp_dir:
            temp_dir = encode_fs(temp_dir)
            build_extension.build_temp = temp_dir
        if lib_dir:
            lib_dir = encode_fs(lib_dir)
            build_extension.build_lib = lib_dir
        if extension is not None:
            build_extension.extensions = [extension]
        return build_extension
