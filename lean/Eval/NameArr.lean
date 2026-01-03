import Lean
open Lean

namespace EvalAuto

def Name.canBeFilename (n : Name) : Bool :=
  n.components.all (fun n =>
    match n with
    | .str _ s =>
      match s.get? 0 with
      | .some _ => s.all (fun c => c.isAlphanum || c == '_' || c == '\'')
      | .none => false
    | _ => false)

def Name.uniqRepr (n : Name) : String :=
  let strRepr (s : String) : String :=
    ((s.replace "\\" "\\\\").replace "." "\\d").replace "\n" "\\n"
  let compRepr (c : Name) : String :=
    match c with
    | .anonymous => ""
    | .mkNum _ n => s!"\\{n}"
    | .mkStr _ s => strRepr s
  String.join (n.components.map (fun c => compRepr c ++ "."))

def Name.parseUniqRepr (n : String) : Name :=
  let compParse (s : String) : String ⊕ Nat := Id.run <| do
    let s := s.data
    if s[0]? == '\\' then
      if let .some c := s[1]? then
        if c.isDigit then
          return .inr ((String.toNat? (String.mk (s.drop 1))).getD 0)
    let mut ret := ""
    let mut escape := false
    for c in s do
      if !escape then
        if c != '\\' then
          ret := ret.push c
        else
          escape := true
      else
        escape := false
        match c with
        | '\\' => ret := ret.push '\\'
        | 'd' => ret := ret.push '.'
        | 'n' => ret := ret.push '\n'
        | _ => ret := ret.push c
    return .inl ret
  let components := ((n.splitOn ".").dropLast).map compParse
  components.foldl (fun prev sn =>
    match sn with
    | .inl s => Name.mkStr prev s
    | .inr n => Name.mkNum prev n) .anonymous

def NameArray.repr (ns : Array Name) : String :=
  String.join (ns.map (fun n => Name.uniqRepr n ++ "\n")).toList

def NameArray.parse (repr : String) : Array Name :=
  Array.mk ((repr.splitOn "\n").map Name.parseUniqRepr).dropLast

def NameArray.save (ns : Array Name) (fname : String) : IO Unit := do
  let fd ← IO.FS.Handle.mk fname .write
  fd.putStr (NameArray.repr ns)

def NameArray.load (fname : String) : IO (Array Name) := do
  let fd ← IO.FS.Handle.mk fname .read
  return NameArray.parse (← fd.readToEnd)

end EvalAuto
