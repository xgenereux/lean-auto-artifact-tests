FROM ubuntu:25.10

ENV TZ=America/Los_Angeles

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git wget curl python3.14 python3.14-venv xz-utils zstd \
       texlive-latex-base texlive-pictures \
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
RUN /root/.elan/bin/elan toolchain install 4.27.0-rc1

# Build Lean code dependencies
WORKDIR /home/lean
COPY lean/lakefile.lean lean/lean-toolchain lean/lake-manifest.json ./
RUN . /root/.elan/env && lake resolve-deps
RUN . /root/.elan/env && lake build Mathlib

# Build Lean code
COPY lean/ ./
RUN . /root/.elan/env && lake build

# Copy test scripts
WORKDIR /home
COPY test_scripts test_scripts

# Copy analysis scripts
COPY analysis analysis

CMD ["/home/test_scripts/all_experiments.sh"]