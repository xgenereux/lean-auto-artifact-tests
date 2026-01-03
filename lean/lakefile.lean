import Lake
open Lake DSL

package eval

@[default_target]
lean_lib Eval

require mathlib from git
  "https://github.com/leanprover-community/mathlib4" @ "v4.20.0"

require aesop from git
  "https://github.com/leanprover-community/aesop" @ "forward-eval-redesign-lazy"
