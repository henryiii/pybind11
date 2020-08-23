# -*- coding: utf-8 -*-

from ._version import version_info, __version__
from .commands import get_include, get_cmake_dir


__all__ = (
    "version_info",
    "__version__",
    "get_include",
    "get_cmake_dir",
    "load_ipython_extension",
    "unload_python_extension",
)


def load_ipython_extension(ipython):
    from ._ipython_ext import Pybind11Magics

    ipython.register_magics(Pybind11Magics)


def unload_ipython_extension(ipython):
    from ._ipython_ext import Pybind11Magics

    ipython.unregister_magics(Pybind11Magics)
