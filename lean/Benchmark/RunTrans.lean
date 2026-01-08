/-
Copyright (c) 2026 Jannis Limperg. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Jannis Limperg, Xavier Généreux
-/

import Benchmark.Command
import Benchmark.Trans

/- Uncomment to reveal benchmark parameters. -/
-- #check benchTrans

-- TODO : replace with 6!! (Or at least 5)
-- /- Transitivity benchmark -/
bchmk 3 with pows 5  using trans 0
bchmk 3 with pows 5  using trans 100
