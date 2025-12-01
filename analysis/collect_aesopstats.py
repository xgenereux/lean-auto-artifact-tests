#!/usr/bin/env python
import json
from pathlib import Path
import pandas as pd
from multiprocessing import Pool
import duckdb
import argparse

def process_files_to_parquet(args):
    worker_id, files, output_dir = args
    output_file = output_dir / f"aesopstats_worker_{worker_id}.parquet"

    def record_generator():
        for file in files:
            tactic = file.stem.split(".aesopstats.")[-1]
            with open(file) as f:
                for line in f:
                    try:
                        record = json.loads(line)
                        record["tactic"] = tactic
                        yield record
                    except json.JSONDecodeError:
                        pass

    df = pd.DataFrame(record_generator())
    if len(df) > 0:
        df.to_parquet(output_file, compression="zstd", index=False)
        return len(df), 0, output_file
    return 0, 0, None

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Collect Aesop statistics from JSONL files')
    parser.add_argument('data_dir', type=Path, help='Data directory containing aesopstats files')
    parser.add_argument('output_dir', type=Path, help='Output directory for parquet file')
    args = parser.parse_args()
    
    data_dir = args.data_dir
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    
    files = list(data_dir.rglob("*.aesopstats.*.jsonl"))

    # Distribute files across workers
    num_workers = Pool()._processes or 1
    chunks = [files[i::num_workers] for i in range(num_workers)]
    worker_args = [(i, chunk, output_dir) for i, chunk in enumerate(chunks) if chunk]

    with Pool() as pool:
        results = pool.map(process_files_to_parquet, worker_args)

    total_rows = sum(r[0] for r in results)
    total_errors = sum(r[1] for r in results)
    worker_files = [r[2] for r in results if r[2]]

    # Use DuckDB to merge with union_by_name
    output_file = output_dir / "aesopstats.parquet"
    con = duckdb.connect()
    file_list = ', '.join(f"'{f}'" for f in worker_files)
    con.execute(f"""
        COPY (
            SELECT * FROM read_parquet([{file_list}], union_by_name=true)
        ) TO '{output_file}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    # Clean up worker files
    for f in worker_files:
        f.unlink()

    print(f"Created {output_file} with {total_rows} rows, {total_errors} decode errors")
