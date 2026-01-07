import Eval.CommandAnalysis
import Eval.TestTactics
import Eval.NameArr
import Std.Time

namespace EvalAuto

open Lean Elab Tactic

def runTacticsAtConstantDeclaration
  (name : Name) (tactics : Array (ConstantInfo → TacticM Unit)) : CoreM (Array Result) := do
  if ← isInitializerExecutionEnabled then
    throwError "{decl_name%} :: Running this function with execution of `initialize` code enabled is unsafe"
  let .some modName ← Lean.findModuleOf? name
    | throwError "{decl_name%} :: Cannot find constant {name}"
  let .some uri ← Server.documentUriFromModule? modName
    | throwError "{decl_name%} :: Cannot find module {modName}"
  let .some path := System.Uri.fileUriToPath? uri
    | throwError "{decl_name%} :: URI {uri} of {modName} is not a file"
  let path := path.normalize
  let inputHandle ← IO.FS.Handle.mk path .read
  let input ← inputHandle.readToEnd
  let results : Array (Array Result) ← runWithEffectOfCommands input path.toString (.some 1) (fun _ctx st₁ _st₂ ci => do
    if name != ci.name then
      return .none
    let metaAction (tactic : ConstantInfo → TacticM Unit) : MetaM Result :=
      Term.TermElabM.run' (ctx := { declName? := name }) do
        Result.ofTacticOnExpr ci.type (tactic ci)
    let coreAction tactic : CoreM Result := (metaAction tactic).run'
    let ioAction tactic : IO (Result × _) :=
      (coreAction tactic).toIO {fileName := path.toString, fileMap := FileMap.ofString input } { env := st₁.commandState.env }
    let resultsWithState ← tactics.mapM (fun tactic => ioAction tactic)
    return .some (resultsWithState.map Prod.fst))
  let #[result] := results
    | throwError "{decl_name%} :: Unexpected error"
  return result

structure EvalTacticConfig where
  timeout?      : Option UInt32 := some 30_000
  maxHeartbeats : Nat           := 65536
  tactics       : Array RegisteredTactic
  logFile       : Option String := .none
  resultFile    : Option String := .none
  aesopStatsPrefix : Option String := none
  nonterminates : Array (RegisteredTactic × Name)
  repetitions : Nat := 1

def withTimeout (timeoutMs : UInt32) (cancelTk : IO.CancelToken) (x : IO α) : IO (Option α) := do
  let task ← (some <$> x).asTask
  let cancelTask ← IO.asTask (prio := .dedicated) do
    IO.sleep timeoutMs
    if ! (← IO.checkCanceled) then
      cancelTk.set
    return none
  let result?? ← IO.waitAny [task, cancelTask]
  IO.cancel cancelTask
  EIO.ofExcept result??

def withMaybeTimeout (timeoutMs : UInt32) (cancelTk? : Option IO.CancelToken) (x : IO α) : IO (Option α) := do
  if let some cancelTk := cancelTk? then
    withTimeout timeoutMs cancelTk x
  else
    x

instance : ToString EvalTacticConfig where
  toString : EvalTacticConfig → String
  | ⟨timeout?, maxHeartbeats, tactics, logFile, resultFile, aesopStatsPrefix, nonterminates, repetitions⟩ =>
    let logFileStr :=
      match logFile with
      | .some logFile => s!", logFile := {logFile}"
      | .none => ""
    let resultFileStr :=
      match resultFile with
      | .some resultFile => s!", resultFile := {resultFile}"
      | .none => ""
    let aesopStatsPrefixStr :=
      match aesopStatsPrefix with
      | .some aesopStatsPrefix => s!", aesopStatsPrefix := {aesopStatsPrefix}"
      | .none => ""
    let nontermStr := String.intercalate ",\n" (nonterminates.map (fun (rt, n) => s!"    ({rt}, {n})")).toList
    let nontermStr := if nonterminates.size != 0 then nontermStr ++ "\n" else nontermStr
    s!"\{\n  timeout? := {timeout?}, maxHeartbeats := {maxHeartbeats}, tactics := {tactics}{logFileStr}{resultFileStr}{aesopStatsPrefixStr}, repetitions := {repetitions}" ++
    s!"\n  nonterminates := #[\n{nontermStr}  ]\n}"

def evalTacticsAtModule
  (modName : Name) (filter : ConstantInfo → Bool) (config : EvalTacticConfig) : CoreM Unit:= do
  let logFileHandle? : Option IO.FS.Handle ← config.logFile.mapM (fun fname => IO.FS.Handle.mk fname .write)
  let resultFileHandle? : Option IO.FS.Handle ← config.resultFile.mapM (fun fname => IO.FS.Handle.mk fname .write)
  trace[auto.eval.printConfig] m!"Config = {config}"
  if let .some fhandle := logFileHandle? then
    fhandle.putStrLn s!"Config = {config}"
    fhandle.putStrLn s!"Start time : {← Std.Time.Timestamp.now}"
  let .some uri ← Server.documentUriFromModule? modName
    | throwError "{decl_name%} :: Cannot find module {modName}"
  let .some path := System.Uri.fileUriToPath? uri
    | throwError "{decl_name%} :: URI {uri} of {modName} is not a file"
  let path := path.normalize
  let inputHandle ← IO.FS.Handle.mk path .read
  let input ← inputHandle.readToEnd
  let startTime ← IO.monoMsNow
  let nonterms := Std.HashSet.ofArray config.nonterminates
  let resultss ← runWithEffectOfCommands input path.toString none fun _ctx st₁ _st₂ ci => do
    if ! filter ci then
      return none
    let mut results := #[]
    for _ in [:config.repetitions] do
      let result ← evalAction
        { fileName := path.toString, fileMap := FileMap.ofString input } { env := st₁.commandState.env }
        ci logFileHandle? config nonterms
      results := results.push (ci.name, result)
    return some results
  let results := resultss.flatten
  if let .some fhandle := resultFileHandle? then
    fhandle.putStrLn s!"Total elapsed time : {(← IO.monoMsNow) - startTime} ms"
    fhandle.putStrLn s!"\nSummary:\n"
    for ((name, result), idx) in results.zipIdx do
      let resultStrs := result.map (fun (r, time, hb) => s!"{r.concise} {time} {hb}")
      fhandle.putStrLn s!"{idx} {resultStrs} {Name.uniqRepr name}"
where
  evalAction
    (context : Core.Context) (state : Core.State) (ci : ConstantInfo)
    (logFileHandle? : Option IO.FS.Handle) (config : EvalTacticConfig)
    (nonterms : Std.HashSet (RegisteredTactic × Name)) :
    IO (Array (Result × Nat × Nat)) := do
  config.tactics.zipIdx.mapM fun (tactic, idx) => do
    let metaAction : MetaM Result :=
      Term.TermElabM.run' (ctx := { declName? := ci.name }) do
      withTheReader Core.Context (fun ctx => { ctx with maxHeartbeats := config.maxHeartbeats * 1000 }) do
      withOptions (async.set · false) do
      let aesopStatsFile :=
        match config.aesopStatsPrefix with
        | none => ""
        | some pre => s!"{pre}.{tactic}.jsonl"
      withOptions (Aesop.aesop.stats.file.set · aesopStatsFile) do
      withCurrHeartbeats do
        Result.ofTacticOnExpr ci.type (tactic.toCiTactic ci)
    let coreAction : CoreM Result := do
      trace[auto.eval.printProblem] m!"Testing tactic {idx} || {ci.name} : {ci.type}"
      if let .some fhandle := logFileHandle? then
        fhandle.putStrLn ""
        fhandle.putStrLn s!"Timestamp : {← Std.Time.Timestamp.now}"
        fhandle.putStrLn s!"Testing tactic {idx} || {ci.name} : {← (Lean.Meta.ppExpr ci.type).run'}"
        fhandle.flush
      let result ← do
        if nonterms.contains (tactic, ci.name) then
          return Result.nonterminate
        else
          metaAction.run'
      trace[auto.eval.printResult] m!"{result}"
      return result
    let cancelTk? ← config.timeout?.mapM fun _ => IO.CancelToken.new
    let timeout := config.timeout?.getD 0
    let problemStartTime ← IO.monoMsNow
    let problemStartHb ← IO.getNumHeartbeats
    let result? ← withMaybeTimeout timeout cancelTk? do
      (·.1) <$> coreAction.toIO context state
    let problemTime := (← IO.monoMsNow) - problemStartTime
    let problemHb := (← IO.getNumHeartbeats) - problemStartHb
    let result := result?.getD <| .exception <| .error .missing m!"Timed out after {timeout}ms"
    if let .some fhandle := logFileHandle? then
      fhandle.putStrLn (toString (← MessageData.format m!"{result}\nElapsed time : {problemTime} ms, {problemHb} hb"))
    return (result, problemTime, problemHb)

def readEvalTacticsAtModuleResult (resultFile : String) : CoreM (Array (Name × Array (Result × Nat × Nat))) := do
  let content ← IO.FS.readFile resultFile
  let lines := content.splitOn "\n"
  if lines[2]? != .some "Summary:" || lines[3]? != .some "" then
    throwError "{decl_name%} :: Format of result file changed, please change analysis code. Result file : {resultFile}"
  let lines := (lines.drop 4).filter (fun s => s != "")
  (Array.mk lines).mapM (analyzeLine resultFile)
where
  analyzeLine (fileName line : String) : CoreM (Name × Array (Result × Nat × Nat)) := do
    let line := (line.dropWhile (fun c => c != ' ')).drop 3
    let tr := (line.takeWhile (fun c => c != ']')).toString.splitOn ", "
    let tr : Array (Result × Nat × Nat) ← (Array.mk tr).mapM (fun s => do
      let [sr, st, sh] := s.splitOn " "
        | throwError "s!{decl_name%} :: In file {fileName}, {s} is not of the form `<result> <time> <heartbeats>`"
      match Result.ofConcise? sr, String.toNat? st, String.toNat? sh with
      | .some r, .some t, .some h => return (r, t, h)
      | _, _, _ => throwError s!"{decl_name%} :: In file {fileName}, {s} is not of the form `<result> <time> <heartbeats>`")
    let line := (line.dropWhile (fun c => c != ']')).drop 2 |>.toString
    let name := Name.parseUniqRepr line
    return (name, tr)

end EvalAuto
