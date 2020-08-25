#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Setup script for PyPI; use CMakeFile.txt to build extension modules

import contextlib
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

# Setuptools has to be before distutils
from setuptools import setup

from distutils.command.install_headers import install_headers

class InstallHeadersNested(install_headers):
    def run(self):
        headers = self.distribution.headers or []
        for header in headers:
            # Remove pybind11/include/
            short_header = header.split("/", 2)[-1]

            dst = os.path.join(self.install_dir, os.path.dirname(short_header))
            self.mkpath(dst)
            (out, _) = self.copy_file(header, dst)
            self.outfiles.append(out)


main_headers = glob.glob("pybind11/include/pybind11/*.h")
detail_headers = glob.glob("pybind11/include/pybind11/detail/*.h")
cmake_files = glob.glob("pybind11/share/cmake/pybind11/*.cmake")
headers = main_headers + detail_headers


setup(
    name="pybind11_inplace",
    packages=[],
    headers=headers,
    cmdclass={"install_headers": InstallHeadersNested},
    data_files=[
        ("share/cmake/pybind11", cmake_files),
        ("include/pybind11", main_headers),
        ("include/pybind11/detail", detail_headers),
    ],
)
