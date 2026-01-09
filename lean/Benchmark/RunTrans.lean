/-
Copyright (c) 2026 Jannis Limperg. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Jannis Limperg, Xavier Généreux
-/

import Benchmark.Command
import Benchmark.Trans

/- Uncomment to reveal benchmark parameters. -/
-- #check benchTrans

-- /- Transitivity benchmark -/
bchmk 10 with pows 4  using trans 0
bchmk 10 with pows 4  using trans 100
