#!/bin/bash -l

cxxstd=$1
source /opt/intel/oneapi/setvars.sh

set -ex

python3 -m pip install --upgrade pip
python3 -m pip install -r tests/requirements.txt --prefer-binary

cmake -S . -B build \
  -DPYBIND11_WERROR=ON \
  -DDOWNLOAD_CATCH=ON \
  -DDOWNLOAD_EIGEN=OFF \
  -DCMAKE_CXX_STANDARD=$cxxstd \
  -DCMAKE_CXX_COMPILER=$(which icpc) \
  -DPYTHON_EXECUTABLE=$(python3 -c "import sys; print(sys.executable)")

cmake --build build -j 2

cmake --build build --target check
cmake --build build --target cpptest
cmake --build build --target test_cmake_build
