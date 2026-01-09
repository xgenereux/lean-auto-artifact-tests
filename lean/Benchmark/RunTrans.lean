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
bchmk 3 with [1,2,3,4,5,6,7,8,9,10,11,12]  using trans 0
bchmk 3 with [1,2,3,4,5,6,7,8,9,10,11,12]  using trans 100
