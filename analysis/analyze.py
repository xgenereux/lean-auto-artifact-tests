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
            AVG(o.total - n.total) as time_diff,
            AVG(o.total) / AVG(n.total) as speedup,
            AVG(o.total) as avg_old,
            AVG(n.total) as avg_new
        FROM {old} o
        JOIN {new} n ON o.declaration = n.declaration
    """).fetchone()
    assert result is not None
    time_diff, speedup, avg_old, avg_new = result
    print(f"  Avg old time: {avg_old/1e6:.2f}ms")
    print(f"  Avg new time: {avg_new/1e6:.2f}ms")
    print(f"  Avg time difference (old - new): {time_diff/1e6:.2f}ms")
    print(f"  Avg speedup (old/new): {speedup:.3f}x")

    print("\nTotal time (gatheredresult):")
    result = con.execute(f"""
        SELECT
            AVG(o.time - n.time) as time_diff,
            AVG(o.time::DOUBLE) / AVG(n.time) as speedup,
            AVG(o.time) as avg_old,
            AVG(n.time) as avg_new
        FROM gathered o
        JOIN gathered n ON o.declaration = n.declaration
        WHERE o.tactic = '{old_tactic}' AND n.tactic = '{new_tactic}'
            AND o.declaration IN (SELECT declaration FROM {decls})
    """).fetchone()
    assert result is not None
    time_diff_g, speedup_g, avg_old_g, avg_new_g = result
    print(f"  Avg old time: {avg_old_g:.2f}ms")
    print(f"  Avg new time: {avg_new_g:.2f}ms")
    print(f"  Avg time difference (old - new): {time_diff_g:.2f}ms")
    print(f"  Avg speedup (old/new): {speedup_g:.3f}x")

    print("\nForward reasoning time:")
    result = con.execute(f"""
        SELECT
            AVG(o.forward_time - n.forward_time) as forward_diff,
            AVG(o.forward_time) / AVG(n.forward_time) as forward_speedup,
            AVG(o.forward_time) as avg_old,
            AVG(n.forward_time) as avg_new
        FROM {old} o
        JOIN {new} n ON o.declaration = n.declaration
    """).fetchone()
    assert result is not None
    forward_diff, forward_speedup, avg_old_forward, avg_new_forward = result
    print(f"  Avg old time: {avg_old_forward/1e6:.2f}ms")
    print(f"  Avg new time: {avg_new_forward/1e6:.2f}ms")
    print(f"  Avg time difference (old - new): {forward_diff/1e6:.2f}ms")
    print(f"  Avg speedup (old/new): {forward_speedup:.3f}x")

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
    print("\nGenerating scatter plots...")
    plot_data = con.execute(f"""
        SELECT
            o.total::DOUBLE / n.total as speedup,
            o.forward_time::DOUBLE / n.forward_time as forward_speedup,
            n.forward_success,
            n.forward_total
        FROM {old} o
        JOIN {new} n ON o.declaration = n.declaration
    """).fetchdf()

    speedup_per_sample = plot_data['speedup']
    forward_speedup_per_sample = plot_data['forward_speedup']

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

    # Average time difference by forward rule count
    # Remove outliers using IQR method
    q1 = plot_data['speedup'].quantile(0.25)
    q3 = plot_data['speedup'].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    plot_data_filtered = plot_data[(plot_data['speedup'] >= lower_bound) & (plot_data['speedup'] <= upper_bound)]

    avg_by_success = plot_data_filtered.groupby('forward_success')['speedup'].mean()
    avg_by_total = plot_data_filtered.groupby('forward_total')['speedup'].mean()

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

    con.execute(f"DROP TABLE {decls}")
    con.execute(f"DROP TABLE {old}")
    con.execute(f"DROP TABLE {new}")

# 'useAesopPUnsafeOld', 'useAesopPUnsafeNew', 'useSaturateNewDAss', 'useSaturateOldDAs'
compare_tactics(old_tactic='useAesopPUnsafeOld', new_tactic='useAesopPUnsafeNew', analysis_name='aesop', success_only=False)
compare_tactics(old_tactic='useAesopPUnsafeOld', new_tactic='useAesopPUnsafeNew', analysis_name='aesop', success_only=True)
compare_tactics(old_tactic='useSaturateOldDAs', new_tactic='useSaturateNewDAss', analysis_name='saturate', success_only=False)
compare_tactics(old_tactic='useSaturateOldDAs', new_tactic='useSaturateNewDAss', analysis_name='saturate', success_only=True)
