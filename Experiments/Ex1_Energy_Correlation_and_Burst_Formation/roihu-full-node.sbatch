#!/usr/bin/env bash
#SBATCH --job-name=synthran-ex1
#SBATCH --account=project_2015302
#SBATCH --partition=medium
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=384
#SBATCH --time=08:00:00
#SBATCH --output=ex1-%j.out
#SBATCH --error=ex1-%j.err

set -euo pipefail

module purge
module load python-data/3.12

SUBMIT_ROOT="${SLURM_SUBMIT_DIR:-$PWD}"
SOURCE_REVISION="$(git -C "$SUBMIT_ROOT" rev-parse HEAD)"
WORK_ROOT="$TMPDIR/SynthRAN-${SLURM_JOB_ID}"
ARCHIVE_DIR="${EX1_ARCHIVE_DIR:-$(dirname "$SUBMIT_ROOT")/ex1-archives}"

mkdir -p "$ARCHIVE_DIR"

echo "SynthRAN Experiment 1 · Roihu full-node run"
echo "Job ID            $SLURM_JOB_ID"
echo "Node              $(hostname)"
echo "Source revision   $SOURCE_REVISION"
echo "Submit root       $SUBMIT_ROOT"
echo "Local work root   $WORK_ROOT"
echo "Archive directory $ARCHIVE_DIR"
echo "CPUs allocated    ${SLURM_CPUS_PER_TASK:-unknown}"
echo "Python            $(python3 --version 2>&1)"

# Run the file-heavy campaign on Roihu's node-local NVMe. Clone the exact
# submitted revision so the campaign source fingerprint remains meaningful.
git clone --quiet --local --no-hardlinks "$SUBMIT_ROOT" "$WORK_ROOT"
git -C "$WORK_ROOT" checkout --quiet --detach "$SOURCE_REVISION"
cd "$WORK_ROOT"

python3 - <<'PY'
import os
print(f"CPU affinity       {len(os.sched_getaffinity(0))}")
PY

set +e
srun --ntasks=1 --cpus-per-task="${SLURM_CPUS_PER_TASK}" \
  ./experiment.sh --experiment ex1 --phase all --no-input
RUN_RC=$?
set -e

# Package whatever campaign state exists, even if the scientific run stopped
# early. The tarball is copied back to persistent project scratch before the
# node-local $TMPDIR is destroyed.
ACTIVE="$WORK_ROOT/.synthran/active-experiment.json"
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
        if [[ "$RUN_RC" -eq 0 ]]; then
          STATE="complete"
        else
          STATE="partial"
        fi
        ARCHIVE_NAME="ex1-${CAMPAIGN_ID}-job${SLURM_JOB_ID}-${STATE}.tar.gz"
        LOCAL_ARCHIVE="$TMPDIR/$ARCHIVE_NAME"
        tar -C "$(dirname "$CAMPAIGN_ROOT")" -czf "$LOCAL_ARCHIVE" "$CAMPAIGN_ID"
        (
          cd "$TMPDIR"
          sha256sum "$ARCHIVE_NAME" > "$ARCHIVE_NAME.sha256"
        )
        cp "$LOCAL_ARCHIVE" "$ARCHIVE_DIR/$ARCHIVE_NAME"
        cp "$TMPDIR/$ARCHIVE_NAME.sha256" "$ARCHIVE_DIR/$ARCHIVE_NAME.sha256"
        echo "Archive           $ARCHIVE_DIR/$ARCHIVE_NAME"
        echo "Archive SHA-256   $(cut -d' ' -f1 "$TMPDIR/$ARCHIVE_NAME.sha256")"
      fi
      ;;
    *)
      echo "Refusing to package unexpected campaign path: $CAMPAIGN_ROOT" >&2
      [[ "$RUN_RC" -ne 0 ]] || RUN_RC=2
      ;;
  esac
else
  echo "No campaign metadata was created; nothing to package." >&2
fi

exit "$RUN_RC"
