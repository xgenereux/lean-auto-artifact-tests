import Lean

open Lean

namespace EvalAuto

def Name.getConstsOfModule (module : Name) : CoreM (Array Name) := do
  let mFile ← findOLean module
  unless (← mFile.pathExists) do
    throwError s!"object file '{mFile}' of module {module} does not exist"
  let (mod, _) ← readModuleData mFile
  return mod.constNames

def tallyNamesByModule (names : Array Name) : CoreM (Std.HashMap Name (Array Name)) := do
  let mut ret : Std.HashMap Name (Array Name) := {}
  for name in names do
    let .some modName ← Lean.findModuleOf? name
      | throwError "{decl_name%} :: Cannot find module of {name}"
    let orig := (ret.get? modName).getD #[]
    ret := ret.insert modName (orig.push name)
  return ret

def Name.getCi (name : Name) (parentFunc : Name) : CoreM ConstantInfo := do
  let .some ci := (← getEnv).find? name
    | throwError "{parentFunc} :: Cannot find name {name}"
  return ci

def Name.hasValue (name : Name) (parentFunc : Name) : CoreM Bool := do
  return (← Name.getCi name parentFunc).value?.isSome

def Name.getValue (name : Name) (parentFunc : Name) : CoreM Expr := do
  let .some v := (← Name.getCi name parentFunc).value?
    | throwError "{parentFunc} :: {name} has no value"
  return v

def Name.isTheorem (name : Name) : CoreM Bool := do
  let .some ci := (← getEnv).find? name
    | throwError "Name.isTheorem :: Cannot find name {name}"
  let .thmInfo _ := ci
    | return false
  return true

def Name.isHumanTheorem (name : Name) : CoreM Bool := do
  let hasDeclRange := (← Lean.findDeclarationRanges? name).isSome
  let isTheorem ← Name.isTheorem name
  let notProjFn := !(← Lean.isProjectionFn name)
  return hasDeclRange && isTheorem && notProjFn

def allHumanTheorems : CoreM (Array Name) := do
  let allConsts := (← getEnv).constants.toList.map Prod.fst
  let allHumanTheorems ← allConsts.filterM Name.isHumanTheorem
  return Array.mk allHumanTheorems

def Name.isFromPackage (name : Name) (pkgPrefix : String) : CoreM Bool := do
  let .some mod ← Lean.findModuleOf? name
    | throwError "{decl_name%} :: Cannot find {name}"
  return mod.components[0]? == .some (.str .anonymous pkgPrefix)

def allHumanTheoremsFromPackage (pkgPrefix : String) : CoreM (Array Name) := do
  let allConsts := (← getEnv).constants.toList.map Prod.fst
  let allHumanTheoremsFromPackage ← allConsts.filterM (fun n =>
    return (← Name.isHumanTheorem n) && (← Name.isFromPackage n pkgPrefix))
  return Array.mk allHumanTheoremsFromPackage

def Expr.getUsedTheorems (e : Expr) : CoreM (Array Name) :=
  e.getUsedConstants.filterM Name.isTheorem

def Name.getUsedTheorems (name : Name) : CoreM (Array Name) := do
  let v ← Name.getValue name decl_name%
  Expr.getUsedTheorems v

def Expr.onlyUsesConsts (e : Expr) (names : Array Name) : Bool :=
  e.getUsedConstants.all (fun name => names.contains name)

def Name.onlyUsesConsts (name : Name) (names : Array Name) : CoreM Bool := do
  let v ← Name.getValue name decl_name%
  return Expr.onlyUsesConsts v names

def Name.onlyUsesConstsInType (name : Name) (names : Array Name) : CoreM Bool := do
  let ci ← Name.getCi name decl_name%
  return Expr.onlyUsesConsts ci.type names

def logicConsts : Array Name := #[
    ``True, ``False,
    ``Not, ``And, ``Or, ``Iff,
    ``Eq
  ]

def boolConsts : Array Name := #[
    ``Bool,
    ``true, ``false,
    ``Bool.and, ``Bool.or, ``Bool.xor, ``Bool.not,
    ``BEq, ``BEq.beq, ``bne, ``instBEqOfDecidableEq, ``instDecidableEqBool,
    ``ite, ``cond,
    ``Decidable, ``Decidable.decide
  ]

def natConsts : Array Name := #[
    ``Nat,
    ``OfNat.ofNat, ``instOfNatNat,
    ``Nat.add, ``Nat.sub, ``Nat.mul, ``Nat.div, ``Nat.mod,
    ``HAdd, ``HAdd.hAdd, ``instHAdd, ``instAddNat,
    ``HSub, ``HSub.hSub, ``instHSub, ``instSubNat,
    ``HMul, ``HMul.hMul, ``instHMul, ``instMulNat,
    ``HDiv, ``HDiv.hDiv, ``instHDiv, ``Nat.instDiv,
    ``HMod, ``HMod.hMod, ``instHMod, ``Nat.instMod,
    ``LE, ``LE.le, ``instLENat,
    ``LT, ``LT.lt, ``instLTNat,
    ``GE.ge, ``GT.gt
  ]

def Name.onlyLogicInType (name : Name) :=
  Name.onlyUsesConstsInType name logicConsts

def Name.onlyBoolLogicInType (name : Name) :=
  Name.onlyUsesConstsInType name (logicConsts ++ boolConsts)

def Name.onlyNatBoolLogicInType (name : Name) :=
  Name.onlyUsesConstsInType name (logicConsts ++ boolConsts ++ natConsts)

def analyze : CoreM (Array (Array Name)) := do
  let a ← allHumanTheorems
  let logicThms ← a.filterM Name.onlyLogicInType
  let boolThms ← a.filterM (fun name =>
    return (!(← Name.onlyLogicInType name)) && (← Name.onlyBoolLogicInType name))
  let natThms ← a.filterM (fun name =>
    return (!(← Name.onlyBoolLogicInType name)) && (← Name.onlyNatBoolLogicInType name))
  return #[logicThms, boolThms, natThms]

end EvalAuto
