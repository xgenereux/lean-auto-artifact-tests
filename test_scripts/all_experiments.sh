#!/usr/bin/env bash

# --- Parse required arguments ---
if [ "$#" -lt 2 ]; then
  echo "Illegal number of parameters"
  echo "Usage: $0 <number_of_processors> <path_to_hammertest_repo> [--nMod N] [--static] [--timeM N]
    [--timeT N] [--mem N] [--threads N]"
  exit 1
fi

num_procs=$1
repo_path=$2
shift 2  # remove required args

# --- Default values ---
declare -A flags
flags=(
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
    --threads)
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
rm -f $repo_path/allResults

# Run evaluation
printf "Experiment starts: %(%s)T\n"
/home/test_scripts/tactics.sh $num_procs $repo_path "${flags[nMod]}" "${flags[static]}" "${flags[timeM]}" "${flags[timeT]}" "${flags[mem]}" "${flags[threads]}"
printf "tactics.sh done: %(%s)T\n"

# Gather results
cd $repo_path && lake env lean GatherResults.lean
printf "GatherResults.lean done: %(%s)T\n"
echo

# Analyze experimental results
echo "Analyzing results ..."
echo "(Disabled)"
printf "Result Analysis done: %(%s)T\n"
