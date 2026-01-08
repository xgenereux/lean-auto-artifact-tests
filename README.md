# Artifact for "Incremental Forward Reasoning for White-Box Proof Search"

This is the artifact for the paper

    Incremental Forward Reasoning for White-Box Proof Search

to be published at TACAS 2026.

The artifact is available at <https://doi.org/10.5281/zenodo.18188520>.

## Building

Build the Docker image. This step needs to be performed twice, once on an
X86 machine and once on an ARM64 machine.

```bash
docker build . -t aesop-forward-artifact
# on x86
docker save aesop-forward-artifact -o out/artifact-x86.tar
# or, on arm64
docker save aesop-forward-artifact -o out/artifact-arm64.tar
```

Copy all remaining data to `out/`:

```bash
cp README.artifact.md out/README.md
cp results-natural.tar results-synth.tar out/
```

## Acknowledgements

The natural benchmark is based on [a
benchmark](https://github.com/PratherConid/lean-auto-artifact) for the
paper [Lean-Auto: An Interface Between Lean 4 and Automated Theorem
Provers](https://link.springer.com/chapter/10.1007/978-3-031-98682-6_10) by
Yicheng Qian, Joshua Clune, Clark Barrett and Jeremy Avigad.
