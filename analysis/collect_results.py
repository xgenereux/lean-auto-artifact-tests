#!/usr/bin/env python
import re
import pandas as pd
from pathlib import Path
import argparse

parser = argparse.ArgumentParser(description='Collect results from .result files')
parser.add_argument('data_dir', type=Path, help='Data directory containing result files')
parser.add_argument('output_dir', type=Path, help='Output directory for parquet file')
args = parser.parse_args()

data_dir = args.data_dir
output_dir = args.output_dir
output_dir.mkdir(parents=True, exist_ok=True)

tactics = [
    "testUnknownConstant",
    "useAesop",
    "useAesopPUnsafeNew",
    "useAesopPUnsafeOld",
    "useSaturateNewDAss",
    "useSaturateOldDAs",
]

errors = {"no_match": 0, "wrong_length": 0, "misformatted_result": 0}

def process_lines():
    result_files = list(data_dir.rglob("*.result"))
    for file in result_files:
        with open(file) as f:
            for line in f:
                if not line.strip() or not line[0].isdigit():
                    continue
                match = re.match(r'(\d+)\s+#\[(.*?)\]\s+(.+)', line)
                if not match:
                    errors["no_match"] += 1
                    continue

                _, results_str, decl = match.groups()
                decl = decl.rstrip('.')
                results = results_str.split(', ')

                if len(results) != len(tactics):
                    errors["wrong_length"] += 1
                    continue

                try:
                    for tactic, result in zip(tactics, results):
                        parts = result.split()
                        if len(parts) >= 2:
                            status = parts[0]
                            time = int(parts[1])
                            yield {
                                "tactic": tactic,
                                "declaration": decl,
                                "success": status == "S",
                                "time": time
                            }
                        else:
                            raise StopIteration
                except StopIteration:
                    errors["misformatted_result"] += 1
                    continue

df = pd.DataFrame(process_lines())
output_file = output_dir / "gatheredresult.parquet"
df.to_parquet(output_file, compression="zstd")
print(f"Created {output_file} with {len(df)} rows")
print(f"Errors: {errors}")
