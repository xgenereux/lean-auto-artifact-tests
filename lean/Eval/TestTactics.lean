import Eval.OS
import Eval.CommandAnalysis
import Aesop.Frontend.Tactic
import Aesop.Frontend.Saturate
import Std.Time

namespace EvalAuto

open Lean Elab Tactic

section Filter

open Meta in
def isNotSimpTheorem (name : Name) : CoreM Bool := do
  return !(← getSimpTheorems).lemmaNames.contains (.decl name)

open Meta in
def isNotInstance (name : Name) : CoreM Bool := do
  return ! (← isInstance name)

def isNotPrivate (name : Name) : Bool := ! (isPrivateName name)

open Expr in
def isNotType (name : Name) : Bool := ! (isType (.const name []))

end Filter

section Tactics

  def testUnknownConstant (ci : ConstantInfo) : TacticM Unit := do
    let .some proof := ci.value?
      | throwError "{decl_name%} :: ConstantInfo of {ci.name} has no value"
    let usedConsts := Expr.getUsedConstants proof ++ Expr.getUsedConstants ci.type
    for name in usedConsts do
      if ((← getEnv).find? name).isNone then
        throwError "{decl_name%} :: Proof of {ci.name} contains unknown constant {name}"
    evalTactic (← `(tactic| sorry))

  def useRfl : TacticM Unit := do evalTactic (← `(tactic| intros; rfl))

  def useSimp : TacticM Unit := do evalTactic (← `(tactic| intros; simp))

  def useSimpAll : TacticM Unit := do evalTactic (← `(tactic| intros; simp_all))

  def useSimpAllWithPremises (ci : ConstantInfo) : TacticM Unit := do
    let .some proof := ci.value?
      | throwError "{decl_name%} :: ConstantInfo of {ci.name} has no value"
    let usedThmNames ← (← Expr.getUsedTheorems proof).filterM (fun name =>
      return !(← Name.onlyLogicInType name))
    let mut filteredThmNames := usedThmNames
    filteredThmNames ← filteredThmNames.filterM (isNotSimpTheorem ·)
    filteredThmNames ← filteredThmNames.filterM (isNotInstance ·)
    filteredThmNames := filteredThmNames.filter isNotPrivate
    filteredThmNames := filteredThmNames.filter isNotType
    let usedThmTerms : Array Term := filteredThmNames.map (fun name => ⟨mkIdent name⟩)
    evalTactic (← `(tactic| intros; simp_all [$[$usedThmTerms:term],*]))

  private def mkAesopStxNew (tacticClauses : Array (TSyntax `Aesop.tactic_clause)) : TSyntax `tactic :=
    Unhygienic.run `(tactic| aesop $tacticClauses:Aesop.tactic_clause*)

  private def mkAesopStxOld (tacticClauses : Array (TSyntax `Aesop.tactic_clause)) : TSyntax `tactic :=
  Unhygienic.run `(tactic|
      set_option aesop.dev.statefulForward false in
      aesop $tacticClauses:Aesop.tactic_clause*)

  def useAesop (useNew : Bool) : TacticM Unit := do
    let mut aesopStx : TSyntax `tactic := default
    if useNew then
      aesopStx := mkAesopStxNew #[]
    else
      aesopStx := mkAesopStxOld #[]
    let stx ← `(tactic|intros; $aesopStx)
    evalTactic stx

def mkAddIdentStx_apply (ident : Ident) : TSyntax `Aesop.tactic_clause :=
  let feat := Unhygienic.run `(feature| $ident:ident)
  let rules : TSyntax `Aesop.rule_expr := Unhygienic.run `(rule_expr| $feat:Aesop.feature)
  Unhygienic.run  `(tactic_clause| (add unsafe $rules:Aesop.rule_expr))

def mkAddIdentStx_forward_safe (ident : Ident) : TSyntax `Aesop.tactic_clause :=
  let feat := Unhygienic.run `(feature| $ident:ident)
  let rules : TSyntax `Aesop.rule_expr := Unhygienic.run `(rule_expr| $feat:Aesop.feature)
  Unhygienic.run  `(tactic_clause| (add safe forward $rules:Aesop.rule_expr))

def mkAddIdentStx_forward_unsafe (ident : Ident) : TSyntax `Aesop.tactic_clause :=
  let feat := Unhygienic.run `(feature| $ident:ident)
  let rules : TSyntax `Aesop.rule_expr := Unhygienic.run `(rule_expr| $feat:Aesop.feature)
  Unhygienic.run  `(tactic_clause| (add 99% forward $rules:Aesop.rule_expr))

  def useAesopWithPremises (useNew : Bool)
      (mkAddIdentStx : Ident → TSyntax `Aesop.tactic_clause) (ci : ConstantInfo) :
      TacticM Unit := do
    let .some proof := ci.value?
      | throwError "{decl_name%} :: ConstantInfo of {ci.name} has no value"
    let usedThmNames ← ((← Expr.getUsedTheorems proof).filterM (fun name =>
      return !(← Name.onlyLogicInType name)))
    let mut filteredThmNames := usedThmNames
    filteredThmNames ← filteredThmNames.filterM (isNotSimpTheorem ·)
    filteredThmNames ← filteredThmNames.filterM (isNotInstance ·)
    filteredThmNames := filteredThmNames.filter isNotPrivate
    filteredThmNames := filteredThmNames.filter isNotType
    let usedThmIdents := filteredThmNames.map Lean.mkIdent
    let addClauses := usedThmIdents.map mkAddIdentStx
    let mut aesopStx : TSyntax `tactic := default
    if useNew then
      aesopStx := mkAesopStxNew addClauses
    else
      aesopStx := mkAesopStxOld addClauses
    let stx ← `(tactic| intros; $aesopStx)
    evalTactic stx
  where
    synth : SourceInfo := SourceInfo.synthetic default default false

    open Aesop Frontend Parser in
  private def mkSaturateStxNew (rules : TSyntax ``additionalRules) :
      TSyntax `tactic :=
      let rules? := some rules
    Unhygienic.run `(tactic |
        saturate 10 $[$rules?]?)

  open Aesop Frontend Parser in
  private def mkSaturateStxOld (rules : TSyntax ``additionalRules) :
      TSyntax `tactic :=
      let rules? := some rules
    Unhygienic.run `(tactic|
        set_option aesop.dev.statefulForward false in
        saturate 10 $[$rules?]?)

  open Aesop Frontend Parser in
  def mkAddRulesStx (idents : Array Ident) : (TSyntax ``additionalRules) :=
    let rules := idents.map (fun ident =>
    Unhygienic.run `(additionalRule| $ident:ident))
  Unhygienic.run `(additionalRules| [$rules:additionalRule,*])

  def useSaturate (useNew : Bool) (aesopDis : Bool) (ci : ConstantInfo) :
      TacticM Unit := do
    let .some proof := ci.value?
      | throwError "{decl_name%} :: ConstantInfo of {ci.name} has no value"
    let usedThmNames ← (← Expr.getUsedTheorems proof).filterM (fun name =>
      return !(← Name.onlyLogicInType name))
    let mut filteredThmNames := usedThmNames
    filteredThmNames ← filteredThmNames.filterM (isNotInstance ·)
    filteredThmNames := filteredThmNames.filter isNotPrivate
    filteredThmNames := filteredThmNames.filter isNotType
    let usedThmIdents := filteredThmNames.map Lean.mkIdent
    let addClauses := mkAddRulesStx usedThmIdents
    let mut saturateStx : TSyntax `tactic := default
    if useNew then
      saturateStx := mkSaturateStxNew addClauses
    else
      saturateStx := mkSaturateStxOld addClauses
    let mut stx : TSyntax `tactic.seq := default
    if aesopDis then
      stx ← `(tactic| intros; $saturateStx; aesop)
    else
      stx ← `(tactic| intros; $saturateStx; assumption)
    evalTactic stx
  where
    synth : SourceInfo := SourceInfo.synthetic default default false

  inductive RegisteredTactic where
    | testUnknownConstant
    | useRfl
    | useSimp
    | useSimpAll
    | useSimpAllWithPremises
    | useAesop
    | useAesopWithPremises
    | useAesopPSafeNew
    | useAesopPSafeOld
    | useAesopPUnsafeNew
    | useAesopPUnsafeOld
    | useSaturateNewDAesop
    | useSaturateOldDAesop
    | useSaturateNewDAss
    | useSaturateOldDAss
  deriving BEq, Hashable, Repr

  instance : ToString RegisteredTactic where
    toString : RegisteredTactic → String
    | .testUnknownConstant     => "testUnknownConstant"
    | .useRfl                  => "useRfl"
    | .useSimp                 => "useSimp"
    | .useSimpAll              => "useSimpAll"
    | .useSimpAllWithPremises  => "useSimpAllWithPremises"
    | .useAesop                => "useAesop"
    | .useAesopWithPremises    => "useAesopWithPremises"
    | .useAesopPSafeNew        => "useAesopPSafeNew"
    | .useAesopPSafeOld        => "useAesopPSafeOld"
    | .useAesopPUnsafeNew      => "useAesopPUnsafeNew"
    | .useAesopPUnsafeOld      => "useAesopPUnsafeOld"
    | .useSaturateNewDAesop    => "useSaturateNewDAesop"
    | .useSaturateOldDAesop    => "useSaturateOldDAesop"
    | .useSaturateNewDAss      => "useSaturateNewDAss"
    | .useSaturateOldDAss      => "useSaturateOldDAs"

  def RegisteredTactic.toCiTactic : RegisteredTactic → ConstantInfo → TacticM Unit
    | .testUnknownConstant     => EvalAuto.testUnknownConstant
    | .useRfl                  => fun _ => EvalAuto.useRfl
    | .useSimp                 => fun _ => EvalAuto.useSimp
    | .useSimpAll              => fun _ => EvalAuto.useSimpAll
    | .useSimpAllWithPremises  => EvalAuto.useSimpAllWithPremises
    | .useAesop                => fun _ => EvalAuto.useAesop true
    | .useAesopWithPremises    => EvalAuto.useAesopWithPremises true mkAddIdentStx_apply
    | .useAesopPSafeNew        => EvalAuto.useAesopWithPremises true mkAddIdentStx_forward_safe
    | .useAesopPSafeOld        => EvalAuto.useAesopWithPremises false mkAddIdentStx_forward_safe
    | .useAesopPUnsafeNew      => EvalAuto.useAesopWithPremises true mkAddIdentStx_forward_unsafe
    | .useAesopPUnsafeOld      => EvalAuto.useAesopWithPremises false mkAddIdentStx_forward_unsafe
    | .useSaturateNewDAesop    => EvalAuto.useSaturate true true
    | .useSaturateOldDAesop    => EvalAuto.useSaturate false true
    | .useSaturateNewDAss      => EvalAuto.useSaturate true false
    | .useSaturateOldDAss      => EvalAuto.useSaturate false false

end Tactics

end EvalAuto
