FROM ubuntu:22.04

ENV TZ=America/Los_Angeles

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git wget curl python3 python3-pip python3-venv xz-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /home

# Install Python Modules in a new virtual environment `result-analysis-env`
# Use `source /home/result-analysis-env/bin/activate` to activate the environment
RUN python3 -m venv result-analysis-env \
  && . result-analysis-env/bin/activate \
  && pip install pandas numpy matplotlib

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
RUN . /root/.elan/env \
  && lake resolve-deps \
  && lake build Mathlib Auto

# Build lean_hammertest_lw
COPY lean_hammertest_lw/ ./
RUN . /root/.elan/env && lake build

# Copy Test Scripts
WORKDIR /home
COPY test_scripts test_scripts

# Copy Result Analysis Scripts
COPY result_analysis result_analysis

# Add execution privilege
RUN chmod +x test_scripts/*
