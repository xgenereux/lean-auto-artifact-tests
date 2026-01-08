#!/bin/bash

# ==============================================================================
# CONFIGURATION
# ==============================================================================

[[ -f /root/.elan/env ]] && source /root/.elan/env

# Navigate to the lean project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")/lean"
RESULTS_DIR="$(dirname "$SCRIPT_DIR")"  # Parent directory containing lean/ and tests_scripts/
TIMEFORMAT="this took %R seconds"

cd "$PROJECT_DIR" || {
    echo "Error: Could not navigate to $PROJECT_DIR"
    exit 1
}

echo "Running benchmarks in: $(pwd)"
echo "Results will be saved to: $RESULTS_DIR"
echo ""

# Backup lakefile.lean
if [[ -f "lakefile.lean" ]]; then
    cp lakefile.lean lakefile.lean.backup
    echo "Backed up lakefile.lean"
else
    echo "Error: lakefile.lean not found"
    exit 1
fi

# Ensure restoration on exit (even if script fails)
trap 'restore_lakefile' EXIT

restore_lakefile() {
    if [[ -f "lakefile.lean.backup" ]]; then
        mv lakefile.lean.backup lakefile.lean
        echo ""
        echo "Restored original lakefile.lean"
    fi
}

cmd_trans() {
    lake build Benchmark.RunTrans
}

cmd_depth() {
    lake build Benchmark.RunDepth
}

# ==============================================================================
# PARSING LOGIC
# ==============================================================================

parse_lean_output() {
    local prefix=$1
    
    # Output the variable assignments to stdout
    awk -v pre="$prefix" '
        /term size 0\)/      { size=0 }
        /term size 100\)/    { size=100 }
        /StatefulForward: false/ { algo="naive"; next }
        /StatefulForward: true/  { algo="inc"; next }
        /^\([0-9]/ { 
            # This matches the coordinate line starting with (number
            if (size==0 && algo=="naive")   print pre "NAIVE_0=\"" $0 "\""
            if (size==0 && algo=="inc")     print pre "INC_0=\"" $0 "\""
            if (size==100 && algo=="naive") print pre "NAIVE_100=\"" $0 "\""
            if (size==100 && algo=="inc")   print pre "INC_100=\"" $0 "\""
        }
    '
}

# ==============================================================================
# FUNCTION TO RUN BENCHMARKS WITH GIVEN PRECOMP SETTING
# ==============================================================================

run_benchmark() {
    local PRECOMP=$1
    local OUTPUT_DIR="$RESULTS_DIR/bench-results-precomp-$PRECOMP"
    local OUTPUT_TEX="benchmark_results.tex"
    
    echo "========================================================================"
    echo "RUNNING BENCHMARKS WITH precompileModules = $PRECOMP"
    echo "========================================================================"
    
    # Modify lakefile.lean (not lakefile.toml)
    echo "--- Setting precompileModules = $PRECOMP in lakefile.lean ---"
    if [[ -f "lakefile.lean" ]]; then
        sed "s/precompileModules := .*/precompileModules := $PRECOMP/" lakefile.lean > lakefile.lean.tmp && mv lakefile.lean.tmp lakefile.lean
        echo "Updated lakefile.lean"
    else
        echo "Warning: lakefile.lean not found"
        return 1
    fi
    
    # Clean build
    echo "--- Deleting .oleans ---"
    lake clean
    echo "--- Building dependencies ---"
    time (lake build Benchmark.Command &&
      lake build Benchmark.Trans && lake build Benchmark.Depth)
    
    # Create directory
    mkdir -p "$OUTPUT_DIR"
    
    echo "--- Running Benchmark: Transitivity ---"
    # Capture output and evaluate it
    eval $(time cmd_trans | parse_lean_output "FIG1_")
    
    echo "--- Running Benchmark: Depth ---"
    eval $(time cmd_depth | parse_lean_output "FIG2_")
    
    {
        echo "Transitivity Benchmark"
        echo "Naive - 0"
        echo $FIG1_NAIVE_0
        echo "Inc - 0"
        echo $FIG1_INC_0
        echo "Naive - 100"
        echo $FIG1_NAIVE_100
        echo "Inc - 100"
        echo $FIG1_INC_100
        echo "Depth Benchmark"
        echo "Naive - 0"
        echo $FIG2_NAIVE_0
        echo "Inc - 0"
        echo $FIG2_INC_0
        echo "Naive - 100"
        echo $FIG2_NAIVE_100
        echo "Inc - 100"
        echo $FIG2_INC_100
    } > "$OUTPUT_DIR/benchmark_results_numbers.txt"
    
    # ==============================================================================
    # LATEX GENERATION
    # ==============================================================================
    
    echo "--- Generating LaTeX File ($OUTPUT_DIR/$OUTPUT_TEX) ---"
    
    cat << EOF > "$OUTPUT_DIR/$OUTPUT_TEX"
\documentclass{article}
\usepackage{pgfplots}
\usepackage{subcaption}
\usepackage{tikz}
\pgfplotsset{compat=1.17}

% Define shapes for the caption logic
\newcommand{\showpgfsquare}{\tikz\draw[orange, fill=none] (0,0) rectangle (1.2ex,1.2ex);}
\newcommand{\showpgfcircle}{\tikz\draw[orange, fill=none] (0,0) circle (0.7ex);}

\begin{document}

\begin{figure}
    \centering
    \begin{tikzpicture}[scale=0.75]
      \begin{axis}[
        xlabel={Number of hypotheses},
        ylabel={Time in ms},
        xmin=1, xmax=16,
        ymin=1, ymax=2^16,
        %xtick={1,2,4,8,16},
        %ytick={2^3,2^5,2^7,2^9,2^11,2^13},
        xmode=log,
        ymode=log,
        log basis x=2,
        log basis y=2,
        legend pos=north west,
        ymajorgrids=true,
        grid style=dashed,
        legend image post style={mark=}
        ]
        % -- PLOT: Size 0, Naive --
        \addplot[color=orange, mark=square, style=densely dashed, mark options={style={solid}}]
          coordinates { $FIG1_NAIVE_0 };
        
        % -- PLOT: Size 0, Incremental --
        \addplot[color=blue, mark=square]
          coordinates { $FIG1_INC_0 };
        
        % -- PLOT: Size 100, Naive --
        \addplot[color=orange, mark=o, style=densely dashed, mark options={style={solid}}]
          coordinates { $FIG1_NAIVE_100 };
        
        % -- PLOT: Size 100, Incremental --
        \addplot[color=blue, mark=o]
          coordinates { $FIG1_INC_100 };
      \end{axis}
    \end{tikzpicture}
  \end{figure}

\begin{figure}
\centering
    \begin{tikzpicture}[scale=0.75]
      \begin{axis}[
        xlabel={Depth},
        ylabel={Time in ms},
        xmin=1, xmax=5,
        ymin=8, ymax=2^10,
        xtick={1,2,3,4,5},
        ymode=log,
        log basis y=2,
        ymajorgrids=true,
        grid style=dashed
        ]
        % -- PLOT: Size 0, Naive --
        \addplot[color=orange, mark=square, style=densely dashed, mark options={style={solid}}]
          coordinates { $FIG2_NAIVE_0 };
        
        % -- PLOT: Size 0, Incremental --
        \addplot[color=blue, mark=square]
          coordinates { $FIG2_INC_0 };
        
        % -- PLOT: Size 100, Naive --
        \addplot[color=orange, mark=o, style=densely dashed, mark options={style={solid}}]
          coordinates { $FIG2_NAIVE_100 };
        
        % -- PLOT: Size 100, Incremental --
        \addplot[color=blue, mark=o]
          coordinates { $FIG2_INC_100 };
      \end{axis}
    \end{tikzpicture}
\end{figure}

\end{document}
EOF
    
    # ==============================================================================
    # COMPILATION
    # ==============================================================================
    
    if command -v pdflatex &> /dev/null; then
        echo "--- Compiling PDF ---"
        (cd "$OUTPUT_DIR" && pdflatex "$OUTPUT_TEX" > /dev/null)
        echo "Done! Generated $OUTPUT_DIR/benchmark_results.pdf"
    else
        echo "Warning: pdflatex not found. The .tex file was created but not compiled."
    fi
    
    echo ""
}

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================

# Run benchmarks with precompileModules = false
run_benchmark "false"

# Run benchmarks with precompileModules = true
run_benchmark "true"

echo "========================================================================"
echo "ALL BENCHMARKS COMPLETE"
echo "========================================================================"
echo "Results saved in:"
echo "  - $RESULTS_DIR/bench-results-precomp-false/"
echo "  - $RESULTS_DIR/bench-results-precomp-true/"