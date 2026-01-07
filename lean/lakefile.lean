import Lake
open Lake DSL

package eval

@[default_target]
lean_lib Eval

require mathlib from git
  "https://github.com/leanprover-community/mathlib4" @ "master"
