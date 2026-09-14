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
NODE_TMP_ROOT="${TMPDIR:-/tmp}"
WORK_ROOT="$NODE_TMP_ROOT/SynthRAN-${SLURM_JOB_ID}"
PERSISTENT_RESULTS_ROOT="$REPO_ROOT/results/experiments/ex1"

mkdir -p "$PERSISTENT_RESULTS_ROOT"

echo "SynthRAN Experiment 1 · Roihu"
echo "Job ID              $SLURM_JOB_ID"
echo "Node                $(hostname)"
echo "Repository          $REPO_ROOT"
echo "Source revision     $SOURCE_REVISION"
echo "Node-local work     $WORK_ROOT"
echo "Tarball destination $PERSISTENT_RESULTS_ROOT"
echo "CPUs allocated      ${SLURM_CPUS_PER_TASK:-unknown}"
echo "Python              $(python3 --version 2>&1)"

# Run the file-heavy campaign on node-local storage. Clone the exact submitted
# revision so the scientific source fingerprint is tied to the submitted commit.
git clone --quiet --local --no-hardlinks "$REPO_ROOT" "$WORK_ROOT"
git -C "$WORK_ROOT" checkout --quiet --detach "$SOURCE_REVISION"
cd "$WORK_ROOT"

python3 - <<'PY'
import os
print(f"CPU affinity         {len(os.sched_getaffinity(0))}")
PY

set +e
srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK:-1}" \
  ./experiment.sh --experiment ex1 --phase all --no-input
RUN_RC=$?
set -e

ACTIVE="$WORK_ROOT/.synthran/active-experiment.json"
ARCHIVE_RC=0

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
        ARCHIVE="$PERSISTENT_RESULTS_ROOT/${CAMPAIGN_ID}.tar.gz"
        PARTIAL="${ARCHIVE}.partial"

        rm -f "$PARTIAL"
        echo "Packing Experiment 1 campaign"
        if tar -C "$(dirname "$CAMPAIGN_ROOT")" -czf "$PARTIAL" "$CAMPAIGN_ID"; then
          mv "$PARTIAL" "$ARCHIVE"
          echo "Ex1 tarball          $ARCHIVE"
          echo "Tarball size         $(du -h "$ARCHIVE" | awk '{print $1}')"
        else
          rm -f "$PARTIAL"
          echo "Failed to create Experiment 1 tarball." >&2
          ARCHIVE_RC=70
        fi
      else
        echo "Campaign metadata points to a missing directory: $CAMPAIGN_ROOT" >&2
        ARCHIVE_RC=2
      fi
      ;;
    *)
      echo "Refusing unexpected campaign path: $CAMPAIGN_ROOT" >&2
      ARCHIVE_RC=2
      ;;
  esac
else
  echo "No campaign metadata was created." >&2
  ARCHIVE_RC=2
fi

if [[ "$RUN_RC" -ne 0 ]]; then
  echo "Experiment 1 exited with status $RUN_RC." >&2
  echo "Any campaign directory that existed was still packed for diagnosis." >&2
  exit "$RUN_RC"
fi

exit "$ARCHIVE_RC"
