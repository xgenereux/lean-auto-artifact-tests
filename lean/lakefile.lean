import Lake
open Lake DSL

package eval where
  precompileModules := false

@[default_target]
lean_lib Eval

lean_lib Benchmark

require mathlib from git
  "https://github.com/leanprover-community/mathlib4" @ "master"
