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
  cat <<'EOF_USAGE'
Usage: ./experiment.sh [options]

Standalone SynthRAN scientific experiment runner.

Options:
  --experiment <id>   Experiment id (ex1 or ex2)
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

Experiment 2 phases:
  prepare
  qualification
  calibration
  freeze
  confirmation
  analysis
  all

Experiment 1 is local-only. Experiment 2 discovers the currently accepted
5G testbed from .synthran/active-deployment.json, shows its actual identity and
reservation state, and asks before using it. experiment.sh never reserves,
repairs, rebuilds, power-cycles, or reconfigures infrastructure.
EOF_USAGE
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

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
SYNTHRAN_PYTHON="$(python3 -m synthran.runtime python)"

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
  echo "  2) Ex2  Causal 5G transport"
  echo "          ACTIVE TESTBED · uses the deployment currently accepted by deploy.sh"
  echo
  read -r -p "Select experiment [1-2]: " choice
  case "${choice:-}" in
    1) EXPERIMENT=ex1 ;;
    2) EXPERIMENT=ex2 ;;
    *) echo "Invalid experiment choice" >&2; exit 2 ;;
  esac
fi

case "$EXPERIMENT" in
  ex1|ex2) ;;
  *) echo "Unsupported experiment: $EXPERIMENT" >&2; exit 2 ;;
esac

if [[ -z "$PHASE" ]]; then
  if $NO_INPUT; then
    PHASE=all
  elif [[ "$EXPERIMENT" == ex1 ]]; then
    experiment_section "Experiment 1 · Energy correlation and burst formation"
    cat <<'EOF_EX1'
  1) Qualification               prove the model contract
  2) Power calibration           locate low / knee / high energy regimes
  3) Population calibration      locate the contention transition
  4) Freeze confirmation design  lock the prespecified campaign
  5) Confirmation                execute the frozen treatment matrix
  6) Analysis                    summarize mechanism and uncertainty
  7) Full experiment             run the complete dependency chain
EOF_EX1
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
  else
    experiment_section "Experiment 2 · Causal 5G transport"
    cat <<'EOF_EX2'
  1) Prepare source cohort        build transferable matched workloads locally
  2) Qualification               validate the currently accepted testbed path
  3) Load calibration            select below / near / above competing load
  4) Freeze confirmation design  lock deployment, source, load and analysis
  5) Confirmation                run/resume the 360 matched transport replays
  6) Analysis                    estimate paired timing effects
  7) Full experiment             prepare, validate, calibrate, freeze, run, analyze
EOF_EX2
    echo
    read -r -p "Select phase [7]: " choice
    case "${choice:-7}" in
      1) PHASE=prepare ;;
      2) PHASE=qualification ;;
      3) PHASE=calibration ;;
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
$NO_INPUT && args+=(--no-input)
"$SYNTHRAN_PYTHON" -m synthran.experiments "${args[@]}"
