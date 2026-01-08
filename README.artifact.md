# Artifact for "Incremental Forward Reasoning for White-Box Proof Search"

Artifact for paper #1583 at TACAS 2026.

We claim the available and reusable badge for this artifact.

## Overview

This artifact can be used to reproduce the experimental results of our paper

    Incremental Forward Reasoning for White-Box Proof Search

to be published at TACAS 2026.

It contains:

- A recent version of Aesop that includes both our new, incremental
  forward reasoning implementation and the old, naive implementation.
- A synthetic benchmark that evaluates the performance of our incremental
  forward reasoning implementation against the previous, naive implementation
  on a few custom test cases.
- A natural benchmark that evaluates the performance on human-written Mathlib
  theorems with simulated perfect premise selection.

## Requirements

The artifact can be run on X86 and ARM64 machines.

The synthetic benchmark can be run on commodity hardware.

The natural benchmark evaluates different tactic configurations on over 200k
Mathlib theorems. It can technically be run on commodity hardware, but we
recommend using a large server to keep the evaluation time reasonable. We
used an m8g.metal-48xl AWS instance with 192 CPU cores, on which the benchmark
takes around 6h. The benchmark requires 4GB of RAM per core; the number of
cores used is configurable.

## Structure and Content

The artifact contains:

- `artifact-x86.tar`: X86 Docker image
- `artifact-arm64.tar`: ARM64 Docker image
- `results-natural.tar`: results from the natural benchmark reported in the paper
- `results-synth.tar`: results from the synthetic benchmark reported in the paper

The Docker images are used to run both benchmarks. Their `/home` folders
contain:

- `lean/`: evaluation harness for the natural benchmark.
- `test_scripts/`: scripts used to run the natural benchmark. The main script
  for the natural benchmark is `all_experiments.sh`. The main script for the
  synthetic benchmark is `synth_benchmark.sh`.
- `analysis/`: scripts that collect the natural benchmark results, compute the
  metrics reported in the paper and generate the plots. The main script is
  `analysis/analyze.py`.
- `results/`: After the natural benchmark is run, the `results` folder contains
  two Parquet files with raw data, as well as the analysis results
  (`analysis.txt`) and plots (`plots/`). The `results-natural.tar` file in the
  artifact contains exactly this folder.
- `bench-results-precomp-true/` and `bench-results-precomp-false/`: After the
  synthetic benchmark is run, these directories contain the results with and
  without precompilation enabled.

## Evaluation

### Preparation

Load the Docker image for your machine's architecture:

```bash
docker load -i artifact-x86.tar
# or
docker load -i artifact-arm64.tar
```

Docker may require `sudo` throughout.

### Task: Synthetic Benchmark Smoke Test

```bash
docker run --name syn-smoke aesop-forward-artifact /home/test_scripts/synth_benchmark.sh
```

This command executes the synthetic benchmark. It should finish within TODO min 
with output such as

```
TODO
```

Benchmark results can be copied out of the container with

```
docker cp synth-smoke:/home/bench-results-precomp-true bench-results-precomp-true
docker cp synth-smoke:/home/bench-results-precomp-false bench-results-precomp-false
```

Each directory should contain a text file and a tex file.


### Task: Natural Benchmark Smoke Test

```bash
docker run --init --name nat-smoke aesop-forward-artifact /home/test_scripts/all_experiments.sh --nMod 4
```

This command executes the natural benchmark for only four (rather than all)
Mathlib modules. The `--init` option may be necessary to correctly reap zombie
processes. The command should finish within 20-30min with output such as

```
Experiment starts: 1767897405
tactics.sh done: 1767899590
Gathering results ...
Created /home/results/gatheredresult.parquet with 2070 rows
Errors: {'no_match': 0, 'wrong_length': 0, 'misformatted_result': 0}
Done: 1767899591
Gathering Aesop stats ...
Created /home/results/aesopstats.parquet with 795 rows, 0 decode errors
Done: 1767899596
Copying allTheorems.txt ...
Analyzing results ...
[various harmless warnings]
Done: 1767899604
```

Benchmark results and analysis can be copied out of the container with

```bash
docker cp nat-smoke:/home/results results
```

The `results` directory should contain two Parquet files, a file `analysis.txt`
and a `plots` directory containing various images.

Note: the synthetic and natural benchmarks must be run in different Docker
containers since the synthetic benchmark clears certain Mathlib build products
that are used by the natural benchmark.

### Task: Reproduce Synthetic Benchmark

We run essentially the same command as for the synthetic benchmark smoke test.

```bash
docker run --name syn aesop-forward-artifact /home/test_scripts/synth_benchmark.sh
```

Benchmark results can be copied out of the container with

```
docker cp synth:/home/bench-results-precomp-true bench-results-precomp-true
docker cp synth:/home/bench-results-precomp-false bench-results-precomp-false
```

To produce the graphs used in the paper, compile the tex file in each directory.
The upper graph is for the Transitivity benchmark, the lower one is for the
Depth benchmark

### Task: Reproduce Natural Benchmark

```bash
docker run --init --detach --name nat aesop-forward-artifact /home/test_scripts/all_experiments.sh
```

This command runs the full natural benchmark, which takes around 6h on an
m8g.metal-48xl AWS instance with 192 processors. Once it has finished, results
can be extracted with

```bash
docker cp nat-smoke:/home/results results
```

The data in the `results` directory should match (within reasonable tolerances)
that reported in the paper:

- The file `allTheorems.txt` contains the number of theorems that were
  considered.
- The file `analysis.txt` contains various statistics. In the paper, we report
  the `aesopstats` numbers (collected by Aesop directly, which is more
  accurate for `saturate` in particular) from the "Analysis aesop (only
  successful)" and "Analysis saturate (only successful)" sections.
- Plots used in the paper can be found in the `plots/` directory:
  - Fig. 3a: `aesop_success_only_old_vs_new_time.pdf`
  - Fig. 3b: `saturate_success_only_old_vs_new_time.pdf`
  - Fig. 4: `aesop_success_only_speedup_by_depth_violin.pdf`

The `all_experiments.sh` script accepts the following flags:

- `--procs`: number of processors to use for the evaluation. Default: all
  physical CPUs.
- `--nMod`: number of Mathlib modules to evaluate. Default: all.
- `--static`: when evaluating a limited number of modules, select them
  deterministically. Default: false.
- `--timeM`: per-module timeout in seconds. Default: 5400.
- `--timeT`: per-tactic timeout in seconds. Default: none.
- `--mem`: memory limit for each Lean process. Default: none.
- `--threads`: threads per Lean process. Default: 1.
- `--repetitions`: number of times each tactic is run on each problem.
  Default: 3.
- `--heartbeats`: per-tactic heartbeat limit. This is a deterministic timeout
  mechanism based on memory allocations. Default: 200000 (Lean's default).

### Task: Inspect Forward Reasoning Implementation

```bash
docker run -it --name inspect aesop-forward-artifact bash
```

This command starts a bash shell from which you can explore the artifact.
The Aesop code being evaluated is in

    /home/lean/.lake/packages/aesop

It is also available as commit `fa78cf032194308a950a264ed87b422a2a7c1c6c` at

https://github.com/leanprover-community/aesop/tree/fa78cf032194308a950a264ed87b422a2a7c1c6c

### Cleanup

Remove Docker containers:

```bash
docker container rm [syn-smoke nat-smoke ...]
```

To list all containers:

```bash
docker container ls -a
```

Once all containers are deleted, the image can be removed:

```bash
docker image rm aesop-forward-artifact
```

## Acknowledgements

The natural benchmark is based on [a
benchmark](https://github.com/PratherConid/lean-auto-artifact) for the
paper [Lean-Auto: An Interface Between Lean 4 and Automated Theorem
Provers](https://link.springer.com/chapter/10.1007/978-3-031-98682-6_10) by
Yicheng Qian, Joshua Clune, Clark Barrett and Jeremy Avigad.
