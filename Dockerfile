FROM ubuntu:25.10

ENV TZ=America/Los_Angeles

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git wget curl python3.14 python3.14-venv xz-utils zstd \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /home

# Create venv for the analysis scripts
COPY analysis/requirements.txt /home/requirements.txt
RUN python3.14 -m venv /home/venv \
  && /home/venv/bin/pip install -r /home/requirements.txt \
  && rm /home/requirements.txt

# Install Elan
RUN wget -q https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh \
  && bash elan-init.sh -y --default-toolchain=none \
  && rm elan-init.sh

# Install Lean (redundant, but better caching)
RUN /root/.elan/bin/elan toolchain install 4.20.0

# Build lean_hammertest_lw dependencies
WORKDIR /home/lean_hammertest_lw
COPY lean_hammertest_lw/lakefile.lean \
  lean_hammertest_lw/lean-toolchain \
  lean_hammertest_lw/lake-manifest.json \
  ./
RUN . /root/.elan/env && lake resolve-deps
RUN . /root/.elan/env && lake build Mathlib Auto

# Build lean_hammertest_lw
COPY lean_hammertest_lw/ ./
RUN . /root/.elan/env && lake build

# Copy test scripts
WORKDIR /home
COPY test_scripts test_scripts

# Copy analysis scripts
COPY analysis analysis
