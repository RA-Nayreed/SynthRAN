#!/usr/bin/env bash
#SBATCH --job-name=synthran-ex1
#SBATCH --account=project_2015302
#SBATCH --partition=medium
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=384
#SBATCH --time=02:00:00
#SBATCH --output=ex1-%j.out
#SBATCH --error=ex1-%j.err

set -euo pipefail

module purge
module load python-data/3.12

resolve_repo_root() {
  local candidate=""

  if [[ -n "${SYNTHRAN_REPO_ROOT:-}" ]]; then
    candidate="$SYNTHRAN_REPO_ROOT"
    if git -C "$candidate" rev-parse --show-toplevel >/dev/null 2>&1; then
      git -C "$candidate" rev-parse --show-toplevel
      return 0
    fi
  fi

  if command -v scontrol >/dev/null 2>&1 && [[ -n "${SLURM_JOB_ID:-}" ]]; then
    candidate="$(
      scontrol show job -o "$SLURM_JOB_ID" 2>/dev/null \
        | tr ' ' '\n' \
        | sed -n 's/^Command=//p' \
        | head -n1
    )"
    if [[ -n "$candidate" && -e "$candidate" ]]; then
      candidate="$(dirname "$(readlink -f "$candidate")")"
      if git -C "$candidate" rev-parse --show-toplevel >/dev/null 2>&1; then
        git -C "$candidate" rev-parse --show-toplevel
        return 0
      fi
    fi
  fi

  for candidate in "${SLURM_SUBMIT_DIR:-}" "$PWD"; do
    [[ -n "$candidate" ]] || continue
    if git -C "$candidate" rev-parse --show-toplevel >/dev/null 2>&1; then
      git -C "$candidate" rev-parse --show-toplevel
      return 0
    fi
  done

  echo "Unable to locate the SynthRAN repository." >&2
  echo "Submit this file by path, or export SYNTHRAN_REPO_ROOT=/path/to/SynthRAN." >&2
  return 1
}

REPO_ROOT="$(resolve_repo_root)"
SOURCE_REVISION="$(git -C "$REPO_ROOT" rev-parse HEAD)"
WORK_ROOT="$TMPDIR/SynthRAN-${SLURM_JOB_ID}"
PERSISTENT_RESULTS_ROOT="$REPO_ROOT/results/experiments/ex1"

DUCKBURG_SYNC="${SYNTHRAN_DUCKBURG_SYNC:-1}"
DUCKBURG_TARGET="${SYNTHRAN_DUCKBURG_TARGET:-rnayreed@duckburg.net.cit.tum.de}"
DUCKBURG_PORT="${SYNTHRAN_DUCKBURG_PORT:-10022}"
DUCKBURG_RESULTS_ROOT="${SYNTHRAN_DUCKBURG_RESULTS_ROOT:-SynthRAN/results/experiments/ex1}"
DUCKBURG_IDENTITY="${SYNTHRAN_DUCKBURG_IDENTITY:-}"

SSH_ARGS=(
  -p "$DUCKBURG_PORT"
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o StrictHostKeyChecking=accept-new
)
RSYNC_RSH="ssh -p $DUCKBURG_PORT -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new"
if [[ -n "$DUCKBURG_IDENTITY" ]]; then
  SSH_ARGS+=(-i "$DUCKBURG_IDENTITY" -o IdentitiesOnly=yes)
  RSYNC_RSH+=" -i $DUCKBURG_IDENTITY -o IdentitiesOnly=yes"
fi

mkdir -p "$PERSISTENT_RESULTS_ROOT"

if [[ "$DUCKBURG_SYNC" == "1" ]]; then
  command -v ssh >/dev/null || { echo "ssh is required for Duckburg transfer" >&2; exit 69; }
  command -v rsync >/dev/null || { echo "rsync is required for Duckburg transfer" >&2; exit 69; }
  printf -v REMOTE_RESULTS_Q '%q' "$DUCKBURG_RESULTS_ROOT"
  if ! ssh "${SSH_ARGS[@]}" "$DUCKBURG_TARGET" \
      "mkdir -p $REMOTE_RESULTS_Q && test -w $REMOTE_RESULTS_Q"; then
    echo "Duckburg transfer preflight failed before Experiment 1 started." >&2
    echo "Target: $DUCKBURG_TARGET:$DUCKBURG_RESULTS_ROOT" >&2
    echo "Fix Roihu -> Duckburg SSH authentication, or set SYNTHRAN_DUCKBURG_SYNC=0 for a Roihu-only run." >&2
    exit 69
  fi
fi

echo "SynthRAN Experiment 1 · Roihu"
echo "Job ID              $SLURM_JOB_ID"
echo "Node                $(hostname)"
echo "Repository          $REPO_ROOT"
echo "Source revision     $SOURCE_REVISION"
echo "Node-local work     $WORK_ROOT"
echo "Persistent results  $PERSISTENT_RESULTS_ROOT"
if [[ "$DUCKBURG_SYNC" == "1" ]]; then
  echo "Duckburg results    $DUCKBURG_TARGET:$DUCKBURG_RESULTS_ROOT"
else
  echo "Duckburg sync       disabled by SYNTHRAN_DUCKBURG_SYNC=0"
fi
echo "CPUs allocated      ${SLURM_CPUS_PER_TASK:-unknown}"
echo "Python              $(python3 --version 2>&1)"

# Run the file-heavy campaign on node-local NVMe. Clone the exact submitted
# revision so the scientific source fingerprint is independent of the directory
# from which sbatch was invoked.
git clone --quiet --local --no-hardlinks "$REPO_ROOT" "$WORK_ROOT"
git -C "$WORK_ROOT" checkout --quiet --detach "$SOURCE_REVISION"
cd "$WORK_ROOT"

python3 - <<'PY'
import os
print(f"CPU affinity         {len(os.sched_getaffinity(0))}")
PY

set +e
srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK}" \
  ./experiment.sh --experiment ex1 --phase all --no-input
RUN_RC=$?
set -e

ACTIVE="$WORK_ROOT/.synthran/active-experiment.json"
TRANSFER_RC=0

if [[ -f "$ACTIVE" ]]; then
  CAMPAIGN_ROOT="$(python3 - "$ACTIVE" <<'PY'
import json
import pathlib
import sys
value = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(value.get("campaign_root", ""))
PY
)"

  case "$CAMPAIGN_ROOT" in
    "$WORK_ROOT"/results/experiments/ex1/*)
      if [[ -d "$CAMPAIGN_ROOT" ]]; then
        CAMPAIGN_ID="$(basename "$CAMPAIGN_ROOT")"
        PERSISTENT_CAMPAIGN="$PERSISTENT_RESULTS_ROOT/$CAMPAIGN_ID"

        mkdir -p "$PERSISTENT_CAMPAIGN"
        echo "Persisting complete campaign directory to Roihu shared storage"
        rsync -a --delete --partial "$CAMPAIGN_ROOT/" "$PERSISTENT_CAMPAIGN/"
        echo "Roihu result        $PERSISTENT_CAMPAIGN"

        if [[ "$DUCKBURG_SYNC" == "1" ]]; then
          REMOTE_CAMPAIGN="$DUCKBURG_RESULTS_ROOT/$CAMPAIGN_ID"
          printf -v REMOTE_CAMPAIGN_Q '%q' "$REMOTE_CAMPAIGN"
          ssh "${SSH_ARGS[@]}" "$DUCKBURG_TARGET" "mkdir -p $REMOTE_CAMPAIGN_Q"

          echo "Synchronizing all campaign files to Duckburg"
          if rsync -a --delete --partial --info=stats2 \
              -e "$RSYNC_RSH" \
              "$PERSISTENT_CAMPAIGN/" \
              "$DUCKBURG_TARGET:$REMOTE_CAMPAIGN/"; then
            VERIFY="$(
              rsync -a --delete --checksum --dry-run --itemize-changes \
                -e "$RSYNC_RSH" \
                "$PERSISTENT_CAMPAIGN/" \
                "$DUCKBURG_TARGET:$REMOTE_CAMPAIGN/"
            )"
            if [[ -n "$VERIFY" ]]; then
              echo "Duckburg verification found differences:" >&2
              printf '%s\n' "$VERIFY" >&2
              TRANSFER_RC=70
            else
              echo "Duckburg result     ~/$REMOTE_CAMPAIGN"
              echo "Duckburg transfer   verified byte-for-byte"
            fi
          else
            echo "Duckburg rsync failed. The full campaign remains preserved on Roihu at:" >&2
            echo "  $PERSISTENT_CAMPAIGN" >&2
            TRANSFER_RC=70
          fi
        fi
      else
        echo "Campaign metadata points to a missing directory: $CAMPAIGN_ROOT" >&2
        [[ "$RUN_RC" -ne 0 ]] || RUN_RC=2
      fi
      ;;
    *)
      echo "Refusing unexpected campaign path: $CAMPAIGN_ROOT" >&2
      [[ "$RUN_RC" -ne 0 ]] || RUN_RC=2
      ;;
  esac
else
  echo "No campaign metadata was created." >&2
  [[ "$RUN_RC" -ne 0 ]] || RUN_RC=2
fi

if [[ "$RUN_RC" -ne 0 ]]; then
  exit "$RUN_RC"
fi
exit "$TRANSFER_RC"
