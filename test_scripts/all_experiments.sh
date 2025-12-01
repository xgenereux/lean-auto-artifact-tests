#!/usr/bin/env bash

repo_path="/home/lean_hammertest_lw"

# --- Default values ---
declare -A flags
flags=(
  [procs]=$(sysctl -n hw.physicalcpu 2>/dev/null || grep -c ^processor /proc/cpuinfo 2>/dev/null || echo 1)
  [nMod]=".none"
  [static]="false"
  [timeM]=".none"
  [timeT]=".none"
  [mem]=".none"
  [threads]="20"
)

# --- Regex for positive integers ---
decim_re='^[1-9][0-9]*$'

# --- Parse optional flags ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --nMod|--timeM|--timeT|--mem)
      flag_name="${1/--/}"  # remove leading --
      if [[ -n $2 && $2 =~ $decim_re ]]; then
        flags[$flag_name]="(.some $2)"
        shift
      else
        echo "Error: $1 requires a positive integer"
        exit 1
      fi
      ;;
    --procs|--threads)
      flag_name="${1/--/}"  # remove leading --
      if [[ -n $2 && $2 =~ $decim_re ]]; then
        flags[$flag_name]=$2
        shift
      else
        echo "Error: $1 requires a positive integer"
        exit 1
      fi
      ;;
    --static)
      flag_name="${1/--/}"
      flags[$flag_name]=true
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
  shift
done


# Set up environment for Lean
source /root/.elan/env

# Remove results of previous experiments (if exists)
rm -rf $repo_path/Eval*
rm -rf /home/results

# Run evaluation
printf "Experiment starts: %(%s)T\n"
/home/test_scripts/tactics.sh "${flags[procs]}" $repo_path "${flags[nMod]}" "${flags[static]}" "${flags[timeM]}" "${flags[timeT]}" "${flags[mem]}" "${flags[threads]}"
printf "tactics.sh done: %(%s)T\n"

# Gather results
mkdir -p /home/results
echo "Gathering results ..."
/home/venv/bin/python /home/analysis/collect_results.py "$repo_path/EvalTactics" "/home/results"
printf "Done: %(%s)T\n"

echo "Gathering Aesop stats ..."
/home/venv/bin/python /home/analysis/collect_aesopstats.py "$repo_path/EvalTactics" "/home/results"
printf "Done: %(%s)T\n"

# Analyze results
echo "Analyzing results ..."
/home/venv/bin/python /home/analysis/analyze.py "/home/results" "/home/results" > "/home/results/analysis.txt"
printf "Done: %(%s)T\n"
