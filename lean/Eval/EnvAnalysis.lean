import Lean
import Eval.NameArr

open Lean

namespace EvalAuto

def Environment.newLocalConstants (env₁ env₂ : Environment) :=
  env₂.constants.map₂.toArray.filterMap (fun (name, ci) =>
    if !env₁.constants.map₂.contains name then .some ci else .none)

def mathlibModules : CoreM (Array Name) := do
  let u := (← getEnv).header.moduleNames
  return u.filter (fun name => name.components[0]? == .some `Mathlib)

def allMathlibModuleNamesCanBeFilename : CoreM Bool := do
  let mms ← mathlibModules
  return mms.all Name.canBeFilename

def Array.randPick {α} (xs : Array α) (n : Nat) : IO (Array α) := do
  let mut ret := #[]
  for _ in [0:n] do
    let rd ← IO.rand 0 (xs.size - 1)
    if h : rd < xs.size then
      ret := ret.push (xs[rd]'h)
  return ret

def Array.randPickNodup {α} (xs : Array α) (n : Nat) : IO (Array α) := do
  let mut ret := #[]
  let mut xs := xs
  let n := Nat.min n xs.size
  for i in [0:n] do
    let rd ← IO.rand 0 (xs.size - 1 - i)
    if h : rd < xs.size then
      ret := ret.push (xs[rd]'h)
      xs := xs.set rd (xs[xs.size - 1 - i]) h
  return ret

def Array.pseudoRandPickNodup {α} (xs : Array α) (n : Nat) (gen : StdGen) : Array α × StdGen := Id.run <| do
  let mut ret := #[]
  let mut xs := xs
  let mut gen := gen
  let n := Nat.min n xs.size
  for i in [0:n] do
    let (rd, gen') := randNat gen 0 (xs.size - 1 - i)
    gen := gen'
    if h : rd < xs.size then
      ret := ret.push (xs[rd]'h)
      xs := xs.set rd (xs[xs.size - 1 - i]) h
  return (ret, gen)

end EvalAuto
