import Auto.EvaluateAuto.EnvAnalysis

open Lean EvalAuto

def Pseudo.MathlibModules (num : Nat) (isStatic : Bool) : CoreM (Std.HashSet Name) := do
  let modules ← mathlibModules
  let mut ret := #[]
  if isStatic then
    ret := modules.take num
  else
    ret := (Array.pseudoRandPickNodup modules num ⟨1711426580, 396961328⟩).1
  return Std.HashSet.ofArray ret

-- def Pseudo.randMathlibModules (num : Nat) : CoreM (Std.HashSet Name) := do
--   let modules ← mathlibModules
--   let (ret, _) := Array.pseudoRandPickNodup modules num ⟨1711426580, 396961328⟩
--   return Std.HashSet.ofArray ret

def Pseudo.randMathlibModules?All (num? : Option Nat) (isStatic : Bool) : CoreM (Name → Bool) :=
  match num? with
  | .some num => do return (← Pseudo.MathlibModules num isStatic).contains
  | .none => pure (fun _ => true)
