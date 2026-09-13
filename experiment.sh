#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"

EXPERIMENT=""
PHASE=""
NO_INPUT=false
DRY_RUN=false
VERBOSE=false

usage() {
  cat <<'EOF'
Usage: ./experiment.sh [options]

Standalone SynthRAN scientific experiment runner.

Options:
  --experiment <id>   Experiment id (currently: ex1)
  --phase <phase>     Phase to plan/run
  -n, --no-input      Disable interactive prompts
  --dry-run           Resolve and print the execution plan without running it
  -v, --verbose       Show additional implementation details
  -h, --help          Show this help

Experiment 1 phases:
  qualification
  power-calibration
  population-calibration
  freeze
  confirmation
  analysis
  all

Parallelism is automatic. Independent scientific runs use the maximum safe CPU
capacity available to this process; dependency barriers remain sequential.

The experiment runner never provisions, repairs, reserves, or reconfigures a
5G testbed. Future physical experiment phases may attach read-only to an already
accepted deployment produced by deploy.sh. Experiment 1 is local-only.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --experiment)
      [[ $# -ge 2 ]] || { echo "--experiment requires an id" >&2; exit 2; }
      EXPERIMENT="$2"
      shift 2
      ;;
    --phase)
      [[ $# -ge 2 ]] || { echo "--phase requires a value" >&2; exit 2; }
      PHASE="$2"
      shift 2
      ;;
    -n|--no-input)
      NO_INPUT=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -v|--verbose)
      VERBOSE=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

experiment_section() {
  echo
  echo "$1"
  printf '%*s\n' "${#1}" '' | tr ' ' '-'
}

show_banner() {
  echo
  if [[ -t 1 ]]; then
    printf '\033[1;35m'
  fi
  cat <<'BANNER'
  _____             _   _     _____            _   _
 / ____|           | | | |   |  __ \     /\   | \ | |
| (___  _   _ _ __ | |_| |__ | |__) |   /  \  |  \| |
 \___ \| | | | '_ \| __| '_ \|  _  /   / /\ \ | . ` |
 ____) | |_| | | | | |_| | | | | \ \  / ____ \| |\  |
|_____/ \__, |_| |_|\__|_| |_|_|  \_\/_/    \_\_| \_|
         __/ |
        |___/       scientific experiment suite
BANNER
  if [[ -t 1 ]]; then
    printf '\033[0m'
  fi
}

if [[ -x .venv/bin/python ]]; then
  SYNTHRAN_PYTHON=.venv/bin/python
else
  command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
  python3 -m venv .venv
  SYNTHRAN_PYTHON=.venv/bin/python
fi

show_banner

experiment_section "Preparing the local SynthRAN experiment runtime"
"$SYNTHRAN_PYTHON" -m synthran.runtime experiment --log /tmp/synthran-experiment-bootstrap.log

mkdir -p .synthran
command -v flock >/dev/null || { echo "flock is required to protect experiment campaigns" >&2; exit 1; }
exec 9>.synthran/experiment.lock
if ! flock -n 9; then
  echo "Another SynthRAN experiment controller is already running." >&2
  echo "Inspect it with: pgrep -af 'experiment.sh|synthran.experiments'" >&2
  exit 1
fi
printf '%s\n' "$$" 1>&9

if [[ -z "$EXPERIMENT" ]]; then
  if $NO_INPUT; then
    echo "--no-input requires --experiment" >&2
    exit 2
  fi
  experiment_section "Available experiments"
  echo "  1) Ex1  Energy correlation and burst formation"
  echo "          LOCAL · no deployed testbed required"
  echo
  read -r -p "Select experiment [1]: " choice
  case "${choice:-1}" in
    1) EXPERIMENT=ex1 ;;
    *) echo "Invalid experiment choice" >&2; exit 2 ;;
  esac
fi

if [[ "$EXPERIMENT" != "ex1" ]]; then
  echo "Unsupported experiment: $EXPERIMENT" >&2
  exit 2
fi

if [[ -z "$PHASE" ]]; then
  if $NO_INPUT; then
    PHASE=all
  else
    experiment_section "Experiment 1 · Energy correlation and burst formation"
    cat <<'EOF'
  1) Qualification              prove the model contract
  2) Power calibration          locate low / knee / high energy regimes
  3) Population calibration     locate the contention transition
  4) Freeze confirmation design lock the prespecified campaign
  5) Confirmation               execute the frozen treatment matrix
  6) Analysis                   summarize mechanism and uncertainty
  7) Full experiment            run the complete dependency chain
EOF
    echo
    read -r -p "Select phase [7]: " choice
    case "${choice:-7}" in
      1) PHASE=qualification ;;
      2) PHASE=power-calibration ;;
      3) PHASE=population-calibration ;;
      4) PHASE=freeze ;;
      5) PHASE=confirmation ;;
      6) PHASE=analysis ;;
      7) PHASE=all ;;
      *) echo "Invalid phase choice" >&2; exit 2 ;;
    esac
  fi
fi

COMMAND=run
$DRY_RUN && COMMAND=plan
args=("$COMMAND" --experiment "$EXPERIMENT" --phase "$PHASE")
$DRY_RUN && args+=(--dry-run)
$VERBOSE && args+=(--verbose)

"$SYNTHRAN_PYTHON" -m synthran.experiments "${args[@]}"
