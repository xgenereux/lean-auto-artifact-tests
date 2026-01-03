import Eval.EvalModule
import Eval.OS

namespace EvalAuto

open Lean Elab Tactic

structure EvalTacticOnMathlibConfig where
  timeout?      : Option Std.Time.Millisecond.Offset := some <| 30_1000
  maxHeartbeats : Nat           := 65536
  tactics       : Array RegisteredTactic
  resultFolder  : String
  nprocs        : Nat
  nthreads      : Nat           := 20
  memoryLimitKb : Option Nat    := .none
  timeLimitS    : Option Nat    := .none
  moduleFilter  : Name → Bool   := fun _ => true
  nonterminates : Array (RegisteredTactic × Name)
  repetitions : Nat := 1

def evalTacticsAtMathlibHumanTheorems (config : EvalTacticOnMathlibConfig) : CoreM Unit := do
  let mms := (← mathlibModules).filter config.moduleFilter
  if !(mms.all Name.canBeFilename) then
    throwError "{decl_name%} :: Some modules have extra-ordinary names. Evaluation code needs to be changed!"
  if !(← System.FilePath.isDir config.resultFolder) then
    IO.FS.createDir config.resultFolder
  let evaluateFilesHandle ← IO.FS.Handle.mk (config.resultFolder ++ "/evaluateFiles.txt") .write
  let allTally ← tallyNamesByModule (← allHumanTheorems)
  let mut running := #[]
  for mm in mms do
    evaluateFilesHandle.putStrLn mm.toString
    evaluateFilesHandle.flush
    let nComps := mm.components.length
    let paths := (List.range nComps).map (fun i =>
      String.join <| (mm.components.take (i + 1)).map (fun n => "/" ++ n.toString))
    for extraDirPath in paths.dropLast do
      let dirPath := config.resultFolder ++ extraDirPath
      if !(← System.FilePath.isDir dirPath) then
        IO.FS.createDir dirPath
    let .some extraLogPath := paths.getLast?
      | throwError "evalAtMathlibHumanTheorems :: Module name {mm} has zero components"
    let logPath := config.resultFolder ++ extraLogPath
    let validThms := (allTally.get? mm).getD #[]
    NameArray.save validThms (logPath ++ ".name")
    let ef ← evalFile mm validThms logPath config
    let evalProc ← EvalProc.create "bash" #[]
    if let .some mlimit := config.memoryLimitKb then
      evalProc.stdin.putStrLn s!"ulimit -v {mlimit}"
    if let .some tlimit := config.timeLimitS then
      evalProc.stdin.putStrLn ("echo " ++ bashRepr ef ++ s!" | timeout {tlimit} lake env lean -j{config.nthreads} --stdin")
    else
      evalProc.stdin.putStrLn ("echo " ++ bashRepr ef ++ s!" | lake env lean -j{config.nthreads} --stdin")
    let (_, evalProc) ← evalProc.takeStdin
    running := running.push (mm, evalProc)
    while running.size >= config.nprocs do
      running ← tryWaitOn evaluateFilesHandle running
  while running.size != 0 do
    running ← tryWaitOn evaluateFilesHandle running
where
  tryWaitOn (evaluateFilesHandle : IO.FS.Handle) (running : Array (Name × EvalTakenProc)) : CoreM (Array (Name × _)) := do
    let mut running' := #[]
    for (mm, proc) in running do
      let retCode? ← proc.tryWait
      match retCode? with
      | .some retCode =>
        evaluateFilesHandle.putStrLn s!"{mm} : {retCode}"
        evaluateFilesHandle.flush
      | .none => running' := running'.push (mm, proc)
    return running'
  evalFile
    (mm : Name) (validThms : Array Name)
    (logPath : String) (config : EvalTacticOnMathlibConfig) : CoreM String := do
    let lb := "{"
    let rb := "}"
    let thmsStrs : List String :=
      match validThms.toList.getLast? with
      | .some last =>
        validThms.toList.dropLast.map (fun n => s!"  {repr n},") ++ [s!"  {repr last}"]
      | .none => []
    let nonterms := config.nonterminates
    let nontermsStrs : List String :=
      match nonterms.toList.getLast? with
      | .some last =>
        nonterms.toList.dropLast.map (fun n => s!"  {repr n},") ++ [s!"  {repr last}"]
      | .none => []
    let tacsStr := String.intercalate ", " (config.tactics.map (fun tac => s!"({repr tac})")).toList
    let allImportedModules := Std.HashSet.ofArray (← getEnv).allImportedModuleNames
    let ensureAesop := auto.testTactics.ensureAesop.get (← getOptions)
    if ensureAesop && !allImportedModules.contains `Aesop then
      throwError "{decl_name%} :: Cannot find module `Aesop`"
    let ensureAesopImports := if ensureAesop then #["import Aesop"] else #[]
    let lines := #[
        s!"import {mm}",
        "import Eval.EvalModule"
      ] ++ ensureAesopImports ++ #[
        "open Lean EvalAuto",
        "",
        "def humanThms : Std.HashSet Name := Std.HashSet.ofList ["
      ] ++ thmsStrs ++ #[
        "]",
        "",
        "def nonterms : Array (RegisteredTactic × Name) := #["
      ] ++ nontermsStrs ++ #[
        "]",
        "",
        "def action : CoreM Unit := do",
        s!"  let _ ← evalTacticsAtModule ({repr mm}) (fun ci => humanThms.contains ci.name)",
        s!"    {lb} timeout? := {config.timeout?}, maxHeartbeats := {config.maxHeartbeats}, tactics := #[{tacsStr}],",
        s!"      logFile := {repr (logPath ++ ".log")}, resultFile := {repr (logPath ++ ".result")}, aesopStatsPrefix := {repr (logPath ++ ".aesopstats")},",
        s!"      nonterminates := nonterms, repetitions := {config.repetitions} {rb}",
        "",
        s!"set_option auto.testTactics.ensureAesop {ensureAesop}",
        "",
        "#eval action"
      ]
    return String.intercalate "\n" lines.toList

def readETMHTResult (config : EvalTacticOnMathlibConfig) :
  CoreM (Array (Name × Array (Name × Array (Result × Nat × Nat)))) := do
  let resultFolder := config.resultFolder
  if !(← System.FilePath.isDir resultFolder) then
    throwError "{decl_name%} :: {config.resultFolder} is not a directory"
  let allPaths ← System.FilePath.walkDir resultFolder
  let mut ret := #[]
  for path in allPaths do
    if !(← System.FilePath.isDir path) && path.toString.takeRight 7 == ".result" then
      let content ← readEvalTacticsAtModuleResult path.toString
      let suffix := (path.toString.drop (resultFolder.length + 1)).dropRight 7
      let modName := (suffix.splitOn "/").foldl (fun a b => Name.str a b) .anonymous
      ret := ret.push (modName, content)
  return ret

def readETMHTResultAllowNonRet (config : EvalTacticOnMathlibConfig) :
  CoreM (Array String × Array (Name × Array (Name × Array (Result × Nat × Nat)))) := do
  let resultFolder := config.resultFolder
  if !(← System.FilePath.isDir resultFolder) then
    throwError "{decl_name%} :: {config.resultFolder} is not a directory"
  let allPaths ← System.FilePath.walkDir resultFolder
  let mut ret := #[]
  let mut nonRet := #[]
  for path in allPaths do
    if !(← System.FilePath.isDir path) && path.toString.takeRight 7 == ".result" then
      let raw ← IO.FS.readFile path
      if raw.length == 0 then
        nonRet := nonRet.push (path.toString.dropRight 7)
        continue
      let content ← readEvalTacticsAtModuleResult path.toString
      let suffix := (path.toString.drop (resultFolder.length + 1)).dropRight 7
      let modName := (suffix.splitOn "/").foldl (fun a b => Name.str a b) .anonymous
      ret := ret.push (modName, content)
  return (nonRet, ret)

def gatherETMHTResult (config : EvalTacticOnMathlibConfig) : CoreM Unit := do
  let resultFolder := config.resultFolder
  let saveFile ← IO.FS.Handle.mk (resultFolder ++ "/gatheredResult") .write
  if !(← System.FilePath.isDir resultFolder) then
    throwError "{decl_name%} :: {config.resultFolder} is not a directory"
  let readResult ← readETMHTResult config
  let readResult := (readResult.map Prod.snd).flatMap id
  saveFile.putStrLn "Total elapsed time: Not applicable. This is a gathered result of evalTacticsAtMathlibHumanTheorems"
  saveFile.putStrLn ""
  saveFile.putStrLn "Summary:"
  saveFile.putStrLn ""
  for ((name, result), idx) in readResult.zipIdx do
    let resultStrs := result.map (fun (r, time, hb) => s!"{r.concise} {time} {hb}")
    saveFile.putStrLn s!"{idx} {resultStrs} {Name.uniqRepr name}"

def gatherETMHTResultAllowNonRet (config : EvalTacticOnMathlibConfig) : CoreM Unit := do
  let resultFolder := config.resultFolder
  let saveFile ← IO.FS.Handle.mk (resultFolder ++ "/gatheredResult") .write
  let nonRetFile ← IO.FS.Handle.mk (resultFolder ++ "/nonRetPaths") .write
  if !(← System.FilePath.isDir resultFolder) then
    throwError "{decl_name%} :: {config.resultFolder} is not a directory"
  let (nonRet, readResult) ← readETMHTResultAllowNonRet config
  let readResult := (readResult.map Prod.snd).flatMap id
  saveFile.putStrLn "Total elapsed time: Not applicable. This is a gathered result of evalTacticsAtMathlibHumanTheorems"
  saveFile.putStrLn ""
  saveFile.putStrLn "Summary:"
  saveFile.putStrLn ""
  for ((name, result), idx) in readResult.zipIdx do
    let resultStrs := result.map (fun (r, time, hb) => s!"{r.concise} {time} {hb}")
    saveFile.putStrLn s!"{idx} {resultStrs} {Name.uniqRepr name}"
  for path in nonRet do
    nonRetFile.putStrLn path

def readETMHTEvaluateFiles (config : EvalTacticOnMathlibConfig) : CoreM (Array Name × Array (Name × Nat)) := do
  let resultFolder := config.resultFolder
  let content ← IO.FS.readFile (resultFolder ++ "/evaluateFiles.txt")
  let lines := (content.splitOn "\n").filter (fun line => line != "")
  let mut retStart := #[]
  let mut retEnd := #[]
  let str2Name (s : String) := (s.splitOn ".").foldl (fun cur field => Name.str cur field) Name.anonymous
  for line in lines do
    if line.contains ':' then
      let [name, retCode] := line.splitOn ":"
        | throwError "{decl_name%} :: Unexpected line format, line content : `{line}`"
      let name := name.dropRight 1
      let retCode := retCode.drop 1
      let some retCode := retCode.toNat?
        | throwError "{decl_name%} :: Unexpected line format, line content : `{line}`"
      retEnd := retEnd.push (str2Name name, retCode)
    else
      retStart := retStart.push (str2Name line)
  return (retStart, retEnd)

end EvalAuto
