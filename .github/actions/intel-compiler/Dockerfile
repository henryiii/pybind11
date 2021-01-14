FROM ubuntu:20.04

RUN export DEBIAN_FRONTEND="noninteractive" \
 && apt-get update \
 && apt-get install -y wget build-essential pkg-config cmake ca-certificates gnupg \
 && wget https://apt.repos.intel.com/intel-gpg-keys/GPG-PUB-KEY-INTEL-SW-PRODUCTS-2023.PUB \
 && apt-key add GPG-PUB-KEY-INTEL-SW-PRODUCTS-2023.PUB \
 && echo "deb https://apt.repos.intel.com/oneapi all main" >> /etc/apt/sources.list.d/oneAPI.list \
 && apt-get update \
 && apt-get install -y intel-oneapi-compiler-dpcpp-cpp-and-cpp-classic cmake python3-dev python3-pip python3-numpy python3-pytest \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
