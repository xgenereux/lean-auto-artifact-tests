import Lean
import Eval.EnvAnalysis
import Eval.ConstAnalysis
import Eval.Result
open Lean

register_option auto.testTactics.ensureAesop : Bool := {
  defValue := false
  descr := "Enable/Disable enforcement of importing `aesop`"
}

namespace EvalAuto

open Elab Frontend

def processHeaderEnsuring (header : TSyntax ``Parser.Module.header) (opts : Options) (messages : MessageLog)
    (inputCtx : Parser.InputContext) (trustLevel : UInt32 := 0) (leakEnv loadExts := false) (ensuring : Array Import := #[])
    : IO (Environment × MessageLog) := do
  try
    let env ← importModules (leakEnv := leakEnv) (loadExts := loadExts) (headerToImports header ++ ensuring) opts trustLevel
    pure (env, messages)
  catch e =>
    let env ← mkEmptyEnvironment
    let spos := header.raw.getPos?.getD 0
    let pos  := inputCtx.fileMap.toPosition spos
    pure (env, messages.add { fileName := inputCtx.fileName, data := toString e, pos := pos })

def runWithEffectOfCommandsCore
  (cnt? : Option Nat)
  (action : Context → State → State → ConstantInfo → IO (Option α)) : FrontendM (Array α) := do
  let mut done := false
  let mut ret := #[]
  let mut cnt := 0
  while !done do
    if cnt?.isSome && cnt >= cnt?.getD 0 then
      break
    let prev ← get
    done ← Frontend.processCommand
    let post ← get
    let newConsts := Environment.newLocalConstants prev.commandState.env post.commandState.env
    for newConst in newConsts do
      if let .some result ← action (← read) prev post newConst then
        cnt := cnt + 1
        ret := ret.push result
        if cnt?.isSome && cnt >= cnt?.getD 0 then
          break
  return ret

def runWithEffectOfCommands
  (input : String) (fileName : String) (cnt? : Option Nat)
  (action : Context → State → State → ConstantInfo → IO (Option α)) : CoreM (Array α) := do
  let inputCtx := Parser.mkInputContext input fileName
  let (header, parserState, messages) ← Parser.parseHeader inputCtx
  let mut ensuring := #[]
  let allImportedModules := Std.HashSet.ofArray (← getEnv).allImportedModuleNames
  if auto.testTactics.ensureAesop.get (← getOptions) then
    if !allImportedModules.contains `Aesop then
      throwError "{decl_name%} :: Cannot find module `Aesop`"
    ensuring := ensuring.push { module := `Aesop }
  let (env, messages) ← processHeaderEnsuring header {} messages inputCtx (ensuring := ensuring) (loadExts := true)
  let commandState := Command.mkState env messages {}
  (runWithEffectOfCommandsCore cnt? action { inputCtx }).run'
    { commandState := commandState, parserState := parserState, cmdPos := parserState.pos }

end EvalAuto
