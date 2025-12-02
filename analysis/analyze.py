#!/usr/bin/env python
import duckdb
import matplotlib.pyplot as plt
from pathlib import Path
from statsmodels.api import nonparametric
import argparse

# Parse arguments
parser = argparse.ArgumentParser(description='Analyze Aesop tactic performance')
parser.add_argument('input_dir', type=Path, help='Input directory containing parquet files')
parser.add_argument('output_dir', type=Path, help='Output directory for results and plots')
args = parser.parse_args()

input_dir = args.input_dir
output_dir = args.output_dir

# Create output directory
output_dir.mkdir(parents=True, exist_ok=True)
plots_dir = output_dir / 'plots'
plots_dir.mkdir(exist_ok=True)
print(f"Results will be saved in {output_dir.absolute()}/")

# Connect to DuckDB
con = duckdb.connect()

# Load datasets
print("Loading datasets...")
con.execute(f"CREATE VIEW aesop AS SELECT * FROM '{input_dir / 'aesopstats.parquet'}'")
con.execute(f"CREATE VIEW gathered AS SELECT * FROM '{input_dir / 'gatheredresult.parquet'}'")

# Basic stats
gathered_stats = con.execute("""
    SELECT
        COUNT(*) as total_rows,
        COUNT(DISTINCT declaration) as unique_decls
    FROM gathered
""").fetchone()
assert gathered_stats is not None
print(f"gatheredresult: {gathered_stats[0]} rows, {gathered_stats[1]} declarations")

aesop_stats = con.execute("""
    SELECT
        COUNT(*) as total_rows,
        COUNT(DISTINCT declaration) as unique_decls
    FROM aesop
""").fetchone()
assert aesop_stats is not None
print(f"aesopstats:     {aesop_stats[0]} rows, {aesop_stats[1]} declarations")

print("\n" + "="*80)
print("SANITY CHECKS")
print("="*80)

# Sanity Check: Coverage of successful tactic calls
print("\nCoverage of successful tactic calls in aesopstats.parquet:")
tactics_of_interest = ['useAesopPUnsafeOld', 'useAesopPUnsafeNew', 'useSaturateNewDAss', 'useSaturateOldDAs']

for tactic in tactics_of_interest:
    result = con.execute(f"""
        SELECT
            COUNT(*) as num_successful,
            SUM(CASE WHEN declaration IN (SELECT declaration FROM aesop WHERE tactic = '{tactic}') THEN 1 ELSE 0 END) as num_in_aesop
        FROM gathered
        WHERE tactic = '{tactic}' AND success = true
    """).fetchone()
    assert result is not None
    num_successful, num_in_aesop = result
    print(f"  {tactic}: {num_in_aesop / num_successful * 100:.2f}% ({num_in_aesop}/{num_successful})")

def print_avg_time_diff_ns(successful_only: bool):
    result = con.execute(f"""
        SELECT
            AVG(g.time) AS avg_gathered_time,
            AVG(a.total) AS avg_aesop_time,
        FROM gathered g
        JOIN aesop a ON g.tactic = a.tactic AND g.declaration = a.declaration
        WHERE g.tactic = '{tactic}'
            AND g.time <= 11000 AND a.total <= 11e9
            {"AND g.success" if successful_only else ""}
    """).fetchone()
    assert result is not None
    avg_gathered_time, avg_aesop_time = result
    avg_gathered_time = avg_gathered_time*1e6 # times in gathered are in ms; aesopstats in ns
    abs_diff = avg_gathered_time - avg_aesop_time
    rel_diff = abs_diff / avg_gathered_time
    print(f"  {tactic} (no timeout{" and successful only" if successful_only else ""}):")
    print(f"    Avg gathered time: {avg_gathered_time/1e6:.2f}ms")
    print(f"    Avg aesopstats time: {avg_aesop_time/1e6:.2f}ms")
    print(f"    Avg difference: {abs_diff/1e6:.2f}ms ({rel_diff * 100:.2f}%)")

# Sanity Check: Total time comparison
print("\nRecorded total time (gatheredresult - aesopstats):")
for tactic in tactics_of_interest:
    print_avg_time_diff_ns(successful_only=False)
    print_avg_time_diff_ns(successful_only=True)

# Sanity Check: Time sanity check for samples in aesopstats.parquet
print("\nTimeout prevalence:")
for tactic in tactics_of_interest:
    result = con.execute(f"""
        SELECT
            SUM(CASE WHEN g.time >= 11e3 THEN 1 ELSE 0 END) as over_threshold_gathered,
            SUM(CASE WHEN a.total >= 11e9 THEN 1 ELSE 0 END) as over_threshold_aesop,
            COUNT(*) as total
        FROM gathered g
        JOIN aesop a ON g.declaration = a.declaration AND g.tactic = a.tactic
        WHERE g.tactic = '{tactic}'
    """).fetchone()
    assert result is not None
    over_threshold_gathered, over_threshold_aesop, total = result
    print(f"  {tactic}:")
    print(f"    {over_threshold_gathered}/{total} samples with gathered time >= 11s ({over_threshold_gathered/total*100:.2f}%)")
    print(f"    {over_threshold_aesop}/{total} samples with Aesop time >= 11s ({over_threshold_aesop/total*100:.2f}%)")

def select_decls(*,
        old_tactic: str,
        new_tactic: str,
        success_match: bool,
        success_both: bool,
        aesop_stats: bool,
        timeout: bool) -> str:
    return f"""
        SELECT o.declaration
        FROM gathered o
          JOIN gathered n ON o.declaration = n.declaration
          JOIN aesop ao ON o.declaration = ao.declaration AND o.tactic = ao.tactic
          JOIN aesop an ON n.declaration = an.declaration AND n.tactic = an.tactic
        WHERE
            o.tactic = '{old_tactic}' AND n.tactic = '{new_tactic}'
            {"AND o.success = n.success" if success_match else ""}
            {"AND o.success AND n.success" if success_both else ""}
            {f"AND o.declaration IN (SELECT declaration FROM aesop WHERE tactic = '{old_tactic}') AND o.declaration IN (SELECT declaration FROM aesop WHERE tactic = '{new_tactic}')" if aesop_stats else ""}
            {"AND o.time <= 11e3 AND n.time <= 11e3 AND ao.total <= 11e9 AND an.total <= 11e9" if timeout else ""}
    """

def count_select(select: str) -> int:
    result = con.execute(f"SELECT COUNT(*) FROM ({select})").fetchone()
    assert result is not None
    return result[0]

def compare_tactics(*, old_tactic: str, new_tactic: str, analysis_name: str, success_only=False) -> None:
    """Compare two tactics, optionally filtering for successful samples only."""

    print("\n" + "="*80)
    print(f"Analysis {analysis_name}{" (only successful)" if success_only else ""}")
    print("="*80)

    # Create temp table with declarations included in analysis
    decls = f"{analysis_name}_decls"
    con.execute(f"""
        CREATE TEMP TABLE {decls} AS
        {select_decls(old_tactic=old_tactic, new_tactic=new_tactic,
          aesop_stats=True,
          success_match=True,
          timeout=True,
          success_both=success_only,
          )}
    """)
    con.execute(f"CREATE UNIQUE INDEX {decls}_idx ON {decls} (declaration)")
    num_decls = count_select(f"SELECT * FROM {decls}")

    # Exclusion analysis
    num_base_decls = count_select(select_decls(
        old_tactic=old_tactic, new_tactic=new_tactic,
        aesop_stats=False,
        timeout=False,
        success_match=False,
        success_both=False,
        ))

    num_decls_aesop = count_select(select_decls(
            old_tactic=old_tactic, new_tactic=new_tactic,
            aesop_stats=True,
            timeout=False,
            success_match=False,
            success_both=False,
            ))
    num_excluded_no_aesop = num_base_decls - num_decls_aesop

    num_decls_aesop_timeout = count_select(select_decls(
        old_tactic=old_tactic, new_tactic=new_tactic,
        aesop_stats=True,
        timeout=True,
        success_match=False,
        success_both=False,
        ))
    # We want to count *additional* exclusions
    num_excluded_timeout = num_decls_aesop - num_decls_aesop_timeout

    num_decls_aesop_timeout_success_match = count_select(select_decls(
        old_tactic=old_tactic, new_tactic=new_tactic,
        aesop_stats=True,
        timeout=True,
        success_match=True,
        success_both=False,
        ))
    num_excluded_success_match = num_decls_aesop_timeout - num_decls_aesop_timeout_success_match

    num_excluded_success_both = 0
    if success_only:
        num_decls_aesop_timeout_success_both = count_select(select_decls(
            old_tactic=old_tactic, new_tactic=new_tactic,
            aesop_stats=True,
            timeout=True,
            success_match=True,
            success_both=True,
            ))
        num_excluded_success_both = num_decls_aesop_timeout_success_match - num_decls_aesop_timeout_success_both

    print(f"\nTotal declarations with both old and new results: {num_base_decls}")
    print(f"Excluded (no Aesop stats): {num_excluded_no_aesop} ({num_excluded_no_aesop/num_base_decls*100:.2f}%)")
    print(f"Excluded (any time > 11s): {num_excluded_timeout} ({num_excluded_timeout/num_base_decls*100:.2f}%)")
    print(f"Excluded (different success status): {num_excluded_success_match} ({num_excluded_success_match/num_base_decls*100:.2f}%)")
    print(f"Excluded (not both successful): {num_excluded_success_both} ({num_excluded_success_both/num_base_decls*100:.2f}%)")
    print(f"Included in analysis: {num_decls} ({num_decls/num_base_decls*100:.2f}%)")

    # Create temp tables with computed metrics
    old = f"{analysis_name}_old"
    con.execute(f"""
        CREATE TEMP TABLE {old} AS
        SELECT
            declaration,
            total,
            forwardState + list_sum(list_transform(
                list_filter(ruleStats, r -> r.rule.builder = 'forward'),
                r -> r.elapsed
            )) as forward_time,
            list_count(list_filter(ruleStats, r -> r.rule.builder = 'forward' AND r.successful)) as forward_success,
            list_count(list_filter(ruleStats, r -> r.rule.builder = 'forward')) as forward_total
        FROM aesop
        WHERE tactic = '{old_tactic}' AND declaration IN (SELECT declaration FROM {decls})
    """)

    new = f"{analysis_name}_new"
    con.execute(f"""
        CREATE TEMP TABLE {new} AS
        SELECT
            declaration,
            total,
            forwardState + list_sum(list_transform(
                list_filter(ruleStats, r -> r.rule.builder = 'forward'),
                r -> r.elapsed
            )) as forward_time,
            list_count(list_filter(ruleStats, r -> r.rule.builder = 'forward' AND r.successful)) as forward_success,
            list_count(list_filter(ruleStats, r -> r.rule.builder = 'forward')) as forward_total,
            list_max(list_transform(
                flatten(list_transform(
                    flatten(list_transform(goalStats, g -> g.forwardStateStats.ruleStateStats)),
                    r -> r.clusterStateStats
                )),
                c -> len(c.instantiationStats)
            )) as max_instantiations
        FROM aesop
        WHERE tactic = '{new_tactic}' AND declaration IN (SELECT declaration FROM {decls})
    """)

    # Metrics
    print("\nTotal time (aesopstats):")
    result = con.execute(f"""
        SELECT
            AVG(o.total - n.total) as time_diff_avg,
            MIN(o.total - n.total) as time_diff_min,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY o.total - n.total) as time_diff_p01,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY o.total - n.total) as time_diff_p10,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY o.total - n.total) as time_diff_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY o.total - n.total) as time_diff_p50,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY o.total - n.total) as time_diff_p75,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY o.total - n.total) as time_diff_p90,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY o.total - n.total) as time_diff_p99,
            MAX(o.total - n.total) as time_diff_max,
            AVG(o.total::DOUBLE / n.total) as speedup_avg,
            MIN(o.total::DOUBLE / n.total) as speedup_min,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY o.total::DOUBLE / n.total) as speedup_p01,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY o.total::DOUBLE / n.total) as speedup_p10,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY o.total::DOUBLE / n.total) as speedup_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY o.total::DOUBLE / n.total) as speedup_p50,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY o.total::DOUBLE / n.total) as speedup_p75,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY o.total::DOUBLE / n.total) as speedup_p90,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY o.total::DOUBLE / n.total) as speedup_p99,
            MAX(o.total::DOUBLE / n.total) as speedup_max,
            AVG(o.total) as avg_old,
            AVG(n.total) as avg_new,
            MIN(o.total) as min_old,
            MIN(n.total) as min_new,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY o.total) as p01_old,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY n.total) as p01_new,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY o.total) as p10_old,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY n.total) as p10_new,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY o.total) as p25_old,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY n.total) as p25_new,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY o.total) as p50_old,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY n.total) as p50_new,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY o.total) as p75_old,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY n.total) as p75_new,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY o.total) as p90_old,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY n.total) as p90_new,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY o.total) as p99_old,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY n.total) as p99_new,
            MAX(o.total) as max_old,
            MAX(n.total) as max_new
        FROM {old} o
        JOIN {new} n ON o.declaration = n.declaration
    """).fetchone()
    assert result is not None
    (time_diff_avg, time_diff_min, time_diff_p01, time_diff_p10, time_diff_p25, time_diff_p50, time_diff_p75, time_diff_p90, time_diff_p99, time_diff_max,
     speedup_avg, speedup_min, speedup_p01, speedup_p10, speedup_p25, speedup_p50, speedup_p75, speedup_p90, speedup_p99, speedup_max,
     avg_old, avg_new, min_old, min_new, p01_old, p01_new, p10_old, p10_new, p25_old, p25_new, p50_old, p50_new, p75_old, p75_new, p90_old, p90_new, p99_old, p99_new, max_old, max_new) = result
    print(f"  Old: min={min_old/1e6:.2f}ms, p1={p01_old/1e6:.2f}ms, p10={p10_old/1e6:.2f}ms, p25={p25_old/1e6:.2f}ms, p50={p50_old/1e6:.2f}ms, avg={avg_old/1e6:.2f}ms, p75={p75_old/1e6:.2f}ms, p90={p90_old/1e6:.2f}ms, p99={p99_old/1e6:.2f}ms, max={max_old/1e6:.2f}ms")
    print(f"  New: min={min_new/1e6:.2f}ms, p1={p01_new/1e6:.2f}ms, p10={p10_new/1e6:.2f}ms, p25={p25_new/1e6:.2f}ms, p50={p50_new/1e6:.2f}ms, avg={avg_new/1e6:.2f}ms, p75={p75_new/1e6:.2f}ms, p90={p90_new/1e6:.2f}ms, p99={p99_new/1e6:.2f}ms, max={max_new/1e6:.2f}ms")
    print(f"  Time difference (old - new): min={time_diff_min/1e6:.2f}ms, p1={time_diff_p01/1e6:.2f}ms, p10={time_diff_p10/1e6:.2f}ms, p25={time_diff_p25/1e6:.2f}ms, p50={time_diff_p50/1e6:.2f}ms, avg={time_diff_avg/1e6:.2f}ms, p75={time_diff_p75/1e6:.2f}ms, p90={time_diff_p90/1e6:.2f}ms, p99={time_diff_p99/1e6:.2f}ms, max={time_diff_max/1e6:.2f}ms")
    print(f"  Speedup (old/new): min={speedup_min:.3f}x, p1={speedup_p01:.3f}x, p10={speedup_p10:.3f}x, p25={speedup_p25:.3f}x, p50={speedup_p50:.3f}x, avg={speedup_avg:.3f}x, p75={speedup_p75:.3f}x, p90={speedup_p90:.3f}x, p99={speedup_p99:.3f}x, max={speedup_max:.3f}x")

    print("\nTotal time (gatheredresult):")
    result = con.execute(f"""
        SELECT
            AVG(o.time - n.time) as time_diff_avg,
            MIN(o.time - n.time) as time_diff_min,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY o.time - n.time) as time_diff_p01,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY o.time - n.time) as time_diff_p10,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY o.time - n.time) as time_diff_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY o.time - n.time) as time_diff_p50,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY o.time - n.time) as time_diff_p75,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY o.time - n.time) as time_diff_p90,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY o.time - n.time) as time_diff_p99,
            MAX(o.time - n.time) as time_diff_max,
            AVG(o.time::DOUBLE / n.time) as speedup_avg,
            MIN(o.time::DOUBLE / n.time) as speedup_min,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY o.time::DOUBLE / n.time) as speedup_p01,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY o.time::DOUBLE / n.time) as speedup_p10,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY o.time::DOUBLE / n.time) as speedup_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY o.time::DOUBLE / n.time) as speedup_p50,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY o.time::DOUBLE / n.time) as speedup_p75,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY o.time::DOUBLE / n.time) as speedup_p90,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY o.time::DOUBLE / n.time) as speedup_p99,
            MAX(o.time::DOUBLE / n.time) as speedup_max,
            AVG(o.time) as avg_old,
            AVG(n.time) as avg_new,
            MIN(o.time) as min_old,
            MIN(n.time) as min_new,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY o.time) as p01_old,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY n.time) as p01_new,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY o.time) as p10_old,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY n.time) as p10_new,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY o.time) as p25_old,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY n.time) as p25_new,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY o.time) as p50_old,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY n.time) as p50_new,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY o.time) as p75_old,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY n.time) as p75_new,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY o.time) as p90_old,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY n.time) as p90_new,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY o.time) as p99_old,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY n.time) as p99_new,
            MAX(o.time) as max_old,
            MAX(n.time) as max_new
        FROM gathered o
        JOIN gathered n ON o.declaration = n.declaration
        WHERE o.tactic = '{old_tactic}' AND n.tactic = '{new_tactic}'
            AND o.declaration IN (SELECT declaration FROM {decls})
    """).fetchone()
    assert result is not None
    (time_diff_avg_g, time_diff_min_g, time_diff_p01_g, time_diff_p10_g, time_diff_p25_g, time_diff_p50_g, time_diff_p75_g, time_diff_p90_g, time_diff_p99_g, time_diff_max_g,
     speedup_avg_g, speedup_min_g, speedup_p01_g, speedup_p10_g, speedup_p25_g, speedup_p50_g, speedup_p75_g, speedup_p90_g, speedup_p99_g, speedup_max_g,
     avg_old_g, avg_new_g, min_old_g, min_new_g, p01_old_g, p01_new_g, p10_old_g, p10_new_g, p25_old_g, p25_new_g, p50_old_g, p50_new_g, p75_old_g, p75_new_g, p90_old_g, p90_new_g, p99_old_g, p99_new_g, max_old_g, max_new_g) = result
    print(f"  Old: min={min_old_g:.2f}ms, p1={p01_old_g:.2f}ms, p10={p10_old_g:.2f}ms, p25={p25_old_g:.2f}ms, p50={p50_old_g:.2f}ms, avg={avg_old_g:.2f}ms, p75={p75_old_g:.2f}ms, p90={p90_old_g:.2f}ms, p99={p99_old_g:.2f}ms, max={max_old_g:.2f}ms")
    print(f"  New: min={min_new_g:.2f}ms, p1={p01_new_g:.2f}ms, p10={p10_new_g:.2f}ms, p25={p25_new_g:.2f}ms, p50={p50_new_g:.2f}ms, avg={avg_new_g:.2f}ms, p75={p75_new_g:.2f}ms, p90={p90_new_g:.2f}ms, p99={p99_new_g:.2f}ms, max={max_new_g:.2f}ms")
    print(f"  Time difference (old - new): min={time_diff_min_g:.2f}ms, p1={time_diff_p01_g:.2f}ms, p10={time_diff_p10_g:.2f}ms, p25={time_diff_p25_g:.2f}ms, p50={time_diff_p50_g:.2f}ms, avg={time_diff_avg_g:.2f}ms, p75={time_diff_p75_g:.2f}ms, p90={time_diff_p90_g:.2f}ms, p99={time_diff_p99_g:.2f}ms, max={time_diff_max_g:.2f}ms")
    print(f"  Speedup (old/new): min={speedup_min_g:.3f}x, p1={speedup_p01_g:.3f}x, p10={speedup_p10_g:.3f}x, p25={speedup_p25_g:.3f}x, p50={speedup_p50_g:.3f}x, avg={speedup_avg_g:.3f}x, p75={speedup_p75_g:.3f}x, p90={speedup_p90_g:.3f}x, p99={speedup_p99_g:.3f}x, max={speedup_max_g:.3f}x")

    print("\nForward reasoning time:")
    result = con.execute(f"""
        SELECT
            AVG(o.forward_time - n.forward_time) as forward_diff_avg,
            MIN(o.forward_time - n.forward_time) as forward_diff_min,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY o.forward_time - n.forward_time) as forward_diff_p01,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY o.forward_time - n.forward_time) as forward_diff_p10,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY o.forward_time - n.forward_time) as forward_diff_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY o.forward_time - n.forward_time) as forward_diff_p50,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY o.forward_time - n.forward_time) as forward_diff_p75,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY o.forward_time - n.forward_time) as forward_diff_p90,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY o.forward_time - n.forward_time) as forward_diff_p99,
            MAX(o.forward_time - n.forward_time) as forward_diff_max,
            AVG(o.forward_time::DOUBLE / n.forward_time) as forward_speedup_avg,
            MIN(o.forward_time::DOUBLE / n.forward_time) as forward_speedup_min,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY o.forward_time::DOUBLE / n.forward_time) as forward_speedup_p01,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY o.forward_time::DOUBLE / n.forward_time) as forward_speedup_p10,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY o.forward_time::DOUBLE / n.forward_time) as forward_speedup_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY o.forward_time::DOUBLE / n.forward_time) as forward_speedup_p50,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY o.forward_time::DOUBLE / n.forward_time) as forward_speedup_p75,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY o.forward_time::DOUBLE / n.forward_time) as forward_speedup_p90,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY o.forward_time::DOUBLE / n.forward_time) as forward_speedup_p99,
            MAX(o.forward_time::DOUBLE / n.forward_time) as forward_speedup_max,
            AVG(o.forward_time) as avg_old,
            AVG(n.forward_time) as avg_new,
            MIN(o.forward_time) as min_old,
            MIN(n.forward_time) as min_new,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY o.forward_time) as p01_old,
            percentile_cont(0.01) WITHIN GROUP (ORDER BY n.forward_time) as p01_new,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY o.forward_time) as p10_old,
            percentile_cont(0.10) WITHIN GROUP (ORDER BY n.forward_time) as p10_new,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY o.forward_time) as p25_old,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY n.forward_time) as p25_new,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY o.forward_time) as p50_old,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY n.forward_time) as p50_new,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY o.forward_time) as p75_old,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY n.forward_time) as p75_new,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY o.forward_time) as p90_old,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY n.forward_time) as p90_new,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY o.forward_time) as p99_old,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY n.forward_time) as p99_new,
            MAX(o.forward_time) as max_old,
            MAX(n.forward_time) as max_new
        FROM {old} o
        JOIN {new} n ON o.declaration = n.declaration
    """).fetchone()
    assert result is not None
    (forward_diff_avg, forward_diff_min, forward_diff_p01, forward_diff_p10, forward_diff_p25, forward_diff_p50, forward_diff_p75, forward_diff_p90, forward_diff_p99, forward_diff_max,
     forward_speedup_avg, forward_speedup_min, forward_speedup_p01, forward_speedup_p10, forward_speedup_p25, forward_speedup_p50, forward_speedup_p75, forward_speedup_p90, forward_speedup_p99, forward_speedup_max,
     avg_old_forward, avg_new_forward, min_old_f, min_new_f, p01_old_f, p01_new_f, p10_old_f, p10_new_f, p25_old_f, p25_new_f, p50_old_f, p50_new_f, p75_old_f, p75_new_f, p90_old_f, p90_new_f, p99_old_f, p99_new_f, max_old_f, max_new_f) = result
    print(f"  Old: min={min_old_f/1e6:.2f}ms, p1={p01_old_f/1e6:.2f}ms, p10={p10_old_f/1e6:.2f}ms, p25={p25_old_f/1e6:.2f}ms, p50={p50_old_f/1e6:.2f}ms, avg={avg_old_forward/1e6:.2f}ms, p75={p75_old_f/1e6:.2f}ms, p90={p90_old_f/1e6:.2f}ms, p99={p99_old_f/1e6:.2f}ms, max={max_old_f/1e6:.2f}ms")
    print(f"  New: min={min_new_f/1e6:.2f}ms, p1={p01_new_f/1e6:.2f}ms, p10={p10_new_f/1e6:.2f}ms, p25={p25_new_f/1e6:.2f}ms, p50={p50_new_f/1e6:.2f}ms, avg={avg_new_forward/1e6:.2f}ms, p75={p75_new_f/1e6:.2f}ms, p90={p90_new_f/1e6:.2f}ms, p99={p99_new_f/1e6:.2f}ms, max={max_new_f/1e6:.2f}ms")
    print(f"  Time difference (old - new): min={forward_diff_min/1e6:.2f}ms, p1={forward_diff_p01/1e6:.2f}ms, p10={forward_diff_p10/1e6:.2f}ms, p25={forward_diff_p25/1e6:.2f}ms, p50={forward_diff_p50/1e6:.2f}ms, avg={forward_diff_avg/1e6:.2f}ms, p75={forward_diff_p75/1e6:.2f}ms, p90={forward_diff_p90/1e6:.2f}ms, p99={forward_diff_p99/1e6:.2f}ms, max={forward_diff_max/1e6:.2f}ms")
    print(f"  Speedup (old/new): min={forward_speedup_min:.3f}x, p1={forward_speedup_p01:.3f}x, p10={forward_speedup_p10:.3f}x, p25={forward_speedup_p25:.3f}x, p50={forward_speedup_p50:.3f}x, avg={forward_speedup_avg:.3f}x, p75={forward_speedup_p75:.3f}x, p90={forward_speedup_p90:.3f}x, p99={forward_speedup_p99:.3f}x, max={forward_speedup_max:.3f}x")

    print("\nForward reasoning as proportion of total time:")
    result = con.execute(f"""
        SELECT
            AVG(o.forward_time::DOUBLE / o.total) as old_prop,
            AVG(n.forward_time::DOUBLE / n.total) as new_prop
        FROM {old} o
        JOIN {new} n ON o.declaration = n.declaration
    """).fetchone()
    assert result is not None
    old_prop, new_prop = result
    print(f"  Old: {old_prop*100:.2f}%")
    print(f"  New: {new_prop*100:.2f}%")

    print("\nMax instantiations per sample (new):")
    result = con.execute(f"""
        SELECT
            MIN(n.max_instantiations) as new_min,
            percentile_cont(0.25) WITHIN GROUP (ORDER BY n.max_instantiations) as new_p25,
            percentile_cont(0.50) WITHIN GROUP (ORDER BY n.max_instantiations) as new_p50,
            percentile_cont(0.75) WITHIN GROUP (ORDER BY n.max_instantiations) as new_p75,
            percentile_cont(0.90) WITHIN GROUP (ORDER BY n.max_instantiations) as new_p90,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY n.max_instantiations) as new_p95,
            percentile_cont(0.99) WITHIN GROUP (ORDER BY n.max_instantiations) as new_p99,
            MAX(n.max_instantiations) as new_max,
            AVG(n.max_instantiations) as new_avg
        FROM {new} n
    """).fetchone()
    assert result is not None
    new_min, new_p25, new_p50, new_p75, new_p90, new_p95, new_p99, new_max, new_avg = result
    def fmt(v): return f"{v:.0f}" if v is not None else "N/A"
    print(f"  min={new_min or 0}, p25={fmt(new_p25)}, p50={fmt(new_p50)}, p75={fmt(new_p75)}, p90={fmt(new_p90)}, p95={fmt(new_p95)}, p99={fmt(new_p99)}, max={new_max or 0}, avg={fmt(new_avg)}")

    # Fetch data for scatter plots
    print("\nGenerating plots...")
    plot_data = con.execute(f"""
        SELECT
            o.total as old_total,
            n.total as new_total,
            o.total::DOUBLE / n.total as speedup,
            o.forward_time::DOUBLE / n.forward_time as forward_speedup,
            n.forward_success,
            n.forward_total
        FROM {old} o
        JOIN {new} n ON o.declaration = n.declaration
    """).fetchdf()

    speedup_per_sample = plot_data['speedup']
    forward_speedup_per_sample = plot_data['forward_speedup']

    # Box plot for total time distributions
    plt.figure(figsize=(10, 6))
    plt.boxplot([plot_data['old_total'] / 1e6, plot_data['new_total'] / 1e6],
                tick_labels=['Old', 'New'], showfliers=False)
    plt.ylabel('Total Time (ms)')
    plt.title(f'{analysis_name}: Total Time Distribution')
    plt.yscale('log')
    plt.grid(True, alpha=0.3, axis='y')
    plt.savefig(plots_dir / f'{analysis_name}_total_time_boxplot.png', dpi=150, bbox_inches='tight')
    plt.close()

    plt.figure(figsize=(10, 6))
    plt.scatter(plot_data['forward_success'], speedup_per_sample, alpha=0.5, s=10)
    plt.xlabel('Number of Successful Forward Rules (New)')
    plt.ylabel('Speedup (old / new)')
    plt.title(f"{analysis_name}: Total Time Speedup vs Successful Forward Rules")
    plt.axhline(y=1, color='r', linestyle='--', alpha=0.5)
    plt.savefig(plots_dir / f"{analysis_name}_total_time_vs_success_forward.png", dpi=150, bbox_inches='tight')
    plt.close()

    plt.figure(figsize=(10, 6))
    plt.scatter(plot_data['forward_total'], speedup_per_sample, alpha=0.5, s=10)
    plt.xlabel('Number of Forward Rules (New)')
    plt.ylabel('Speedup (old / new)')
    plt.title(f"{analysis_name}: Total Time Speedup vs Total Forward Rules")
    plt.axhline(y=1, color='r', linestyle='--', alpha=0.5)
    plt.savefig(plots_dir / f"{analysis_name}_total_time_vs_total_forward.png", dpi=150, bbox_inches='tight')
    plt.close()

    plt.figure(figsize=(10, 6))
    plt.scatter(plot_data['forward_success'], forward_speedup_per_sample, alpha=0.5, s=10)
    plt.xlabel('Number of Successful Forward Rules (New)')
    plt.ylabel('Forward Speedup (old / new)')
    plt.title(f"{analysis_name}: Forward Time Speedup vs Successful Forward Rules")
    plt.axhline(y=1, color='r', linestyle='--', alpha=0.5)
    plt.savefig(plots_dir / f"{analysis_name}_forward_time_vs_success_forward.png", dpi=150, bbox_inches='tight')
    plt.close()

    plt.figure(figsize=(10, 6))
    plt.scatter(plot_data['forward_total'], forward_speedup_per_sample, alpha=0.5, s=10)
    plt.xlabel('Number of Forward Rules (New)')
    plt.ylabel('Forward Speedup (old / new)')
    plt.title(f'{analysis_name}: Forward Time Speedup vs Total Forward Rules')
    plt.axhline(y=1, color='r', linestyle='--', alpha=0.5)
    plt.savefig(plots_dir / f'{analysis_name}_forward_time_vs_total_forward.png', dpi=150, bbox_inches='tight')
    plt.close()

    # Scatter plots with LOWESS trend (all data points)
    plt.figure(figsize=(10, 6))
    plt.scatter(plot_data['forward_success'], speedup_per_sample, alpha=0.3, s=5)
    if len(plot_data) > 3:
        smoothed = nonparametric.lowess(speedup_per_sample, plot_data['forward_success'], frac=0.2)
        plt.plot(smoothed[:, 0], smoothed[:, 1], 'r-', linewidth=2, label='LOWESS trend')
        plt.legend()
    plt.xlabel('Number of Successful Forward Rules (New)')
    plt.ylabel('Speedup (old / new)')
    plt.title(f'{analysis_name}: Speedup by Successful Forward Rules')
    plt.axhline(y=1, color='gray', linestyle='--', alpha=0.5)
    plt.grid(True, alpha=0.3)
    plt.savefig(plots_dir / f'{analysis_name}_speedup_by_success_forward.png', dpi=150, bbox_inches='tight')
    plt.close()

    plt.figure(figsize=(10, 6))
    plt.scatter(plot_data['forward_total'], speedup_per_sample, alpha=0.3, s=5)
    if len(plot_data) > 3:
        smoothed = nonparametric.lowess(speedup_per_sample, plot_data['forward_total'], frac=0.2)
        plt.plot(smoothed[:, 0], smoothed[:, 1], 'r-', linewidth=2, label='LOWESS trend')
        plt.legend()
    plt.xlabel('Number of Forward Rules (New)')
    plt.ylabel('Speedup (old / new)')
    plt.title(f'{analysis_name}: Speedup by Total Forward Rules')
    plt.axhline(y=1, color='gray', linestyle='--', alpha=0.5)
    plt.grid(True, alpha=0.3)
    plt.savefig(plots_dir / f'{analysis_name}_speedup_by_total_forward.png', dpi=150, bbox_inches='tight')
    plt.close()

    # Average speedup by forward rule count
    avg_by_success = plot_data.groupby('forward_success')['speedup'].mean()
    avg_by_total = plot_data.groupby('forward_total')['speedup'].mean()

    plt.figure(figsize=(10, 6))
    plt.scatter(avg_by_success.index, avg_by_success.values, s=20, alpha=0.6)
    if len(avg_by_success) > 3:
        smoothed = nonparametric.lowess(avg_by_success.values, avg_by_success.index, frac=0.2)
        plt.plot(smoothed[:, 0], smoothed[:, 1], 'r-', linewidth=2, label='LOWESS trend')
        plt.legend()
    plt.xlabel('Number of Successful Forward Rules (New)')
    plt.ylabel('Avg Speedup (old / new)')
    plt.title(f'{analysis_name}: Average Speedup by Successful Forward Rules')
    plt.axhline(y=1, color='gray', linestyle='--', alpha=0.5)
    plt.grid(True, alpha=0.3)
    plt.savefig(plots_dir / f'{analysis_name}_avg_speedup_by_success_forward.png', dpi=150, bbox_inches='tight')
    plt.close()

    plt.figure(figsize=(10, 6))
    plt.scatter(avg_by_total.index, avg_by_total.values, s=20, alpha=0.6)
    if len(avg_by_total) > 3:
        smoothed = nonparametric.lowess(avg_by_total.values, avg_by_total.index, frac=0.2)
        plt.plot(smoothed[:, 0], smoothed[:, 1], 'r-', linewidth=2, label='LOWESS trend')
        plt.legend()
    plt.xlabel('Number of Forward Rules (New)')
    plt.ylabel('Avg Speedup (old / new)')
    plt.title(f'{analysis_name}: Average Speedup by Total Forward Rules')
    plt.axhline(y=1, color='gray', linestyle='--', alpha=0.5)
    plt.grid(True, alpha=0.3)
    plt.savefig(plots_dir / f'{analysis_name}_avg_speedup_by_total_forward.png', dpi=150, bbox_inches='tight')
    plt.close()

    # Export slowdowns
    print("\nExporting declarations with significant slowdowns...")
    slowdowns = con.execute(f"""
        SELECT
            o.declaration,
            a.file,
            a.syntax,
            o.forward_time / 1e6 as old_time_ms,
            n.forward_time / 1e6 as new_time_ms,
            n.forward_time::DOUBLE / o.forward_time as slowdown
        FROM {old} o
        JOIN {new} n ON o.declaration = n.declaration
        JOIN aesop a ON n.declaration = a.declaration AND a.tactic = '{new_tactic}'
        WHERE n.forward_time > o.forward_time * 1.5
            AND n.forward_time >= 50e6
        ORDER BY slowdown DESC
    """).fetchdf()

    if len(slowdowns) > 0:
        slowdowns_file = output_dir / f"{analysis_name}_slowdowns.csv"
        slowdowns.to_csv(slowdowns_file, index=False)
        print(f"  Exported {len(slowdowns)} slowdowns to {slowdowns_file}")
    else:
        print(f"  No significant slowdowns found")

    con.execute(f"DROP TABLE {decls}")
    con.execute(f"DROP TABLE {old}")
    con.execute(f"DROP TABLE {new}")

# 'useAesopPUnsafeOld', 'useAesopPUnsafeNew', 'useSaturateNewDAss', 'useSaturateOldDAs'
compare_tactics(old_tactic='useAesopPUnsafeOld', new_tactic='useAesopPUnsafeNew', analysis_name='aesop', success_only=False)
compare_tactics(old_tactic='useAesopPUnsafeOld', new_tactic='useAesopPUnsafeNew', analysis_name='aesop', success_only=True)
compare_tactics(old_tactic='useSaturateOldDAs', new_tactic='useSaturateNewDAss', analysis_name='saturate', success_only=False)
compare_tactics(old_tactic='useSaturateOldDAs', new_tactic='useSaturateNewDAss', analysis_name='saturate', success_only=True)
