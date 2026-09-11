#!/usr/bin/env bash
set -euo pipefail
set +m

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" != --worker ]]; then
  RUN_DIR=$1
  SYNTHRAN_PYTHON=$2
  for required in nohup setsid tail; do
    command -v "$required" >/dev/null || { echo "$required is required for deployment process control" >&2; exit 1; }
  done
  : >"$RUN_DIR/ansible.log"
  echo "Deployment continues on this host if the terminal disconnects. Ctrl+C cancels it."
  echo "Full Ansible output: $RUN_DIR/ansible.log"
  echo "Controller output: $RUN_DIR/deployment.log"
  nohup setsid --wait bash "$SCRIPT_DIR/run_deployment.sh" --worker "$@" \
    </dev/null >"$RUN_DIR/deployment.log" 2>&1 &
  WORKER_PID=$!

  cancel_deployment() {
    trap '' INT TERM
    if [[ -n "$WORKER_PID" ]]; then
      kill -TERM "$WORKER_PID" 2>/dev/null || true
      wait "$WORKER_PID" 2>/dev/null || true
    fi
    exit "$1"
  }
  trap 'cancel_deployment 130' INT
  trap 'cancel_deployment 143' TERM
  trap 'exit 129' HUP

  tail --pid="$WORKER_PID" -n +1 -f -- "$RUN_DIR/ansible.log" 9>&- \
    | "$SYNTHRAN_PYTHON" -u "$SCRIPT_DIR/filter_ansible_output.py" 9>&- &
  VIEWER_PID=$!
  WORKER_RC=0
  wait "$WORKER_PID" || WORKER_RC=$?
  WORKER_PID=""
  wait "$VIEWER_PID" || true
  cat "$RUN_DIR/deployment.log"
  exit "$WORKER_RC"
fi

shift
RUN_DIR=$1
SYNTHRAN_PYTHON=$2
CONFIG=$3
ACTIVE_DEPLOYMENT_STATE=$4
WORKLOAD_ONLY=$5
shift 5
DEPLOYMENT_COMMAND=("$@")
CHILD_PID=""
printf '%s\n' "$$" >"$RUN_DIR/controller.pid"

record_exit() {
  local original_status=$?
  local safety_status=0
  local status=$original_status
  trap - EXIT

  if [[ -n "${SYNTHRAN_PRIVATE_DIR:-}" && -d "$RUN_DIR" ]]; then
    "$SYNTHRAN_PYTHON" -m synthran.result_safety \
      --run-dir "$RUN_DIR" --private-dir "$SYNTHRAN_PRIVATE_DIR" || safety_status=$?
  fi
  if (( status == 0 && safety_status != 0 )); then
    status=$safety_status
  fi

  printf '%s\n' "$status" >"$RUN_DIR/controller-exit-code"
  echo "SynthRAN controller exited with status $status; shareable artifacts retained in $RUN_DIR"
  exit "$status"
}

cancel_worker() {
  trap '' INT TERM
  if [[ -n "$CHILD_PID" ]]; then
    kill -TERM -- "-$CHILD_PID" 2>/dev/null || true
    wait "$CHILD_PID" 2>/dev/null || true
  fi
  exit "$1"
}
trap record_exit EXIT
trap 'cancel_worker 130' INT
trap 'cancel_worker 143' TERM

run_step() {
  local status=0
  # Each step owns a process group so cancellation reaches experiment and
  # Ansible descendants as well as the immediate command. Job control is off.
  setsid --wait "$@" <&0 9>&- &
  CHILD_PID=$!
  wait "$CHILD_PID" || status=$?
  CHILD_PID=""
  return "$status"
}

collect_failure_diagnostics() {
  local reason=$1
  local diagnostics_rc=0
  local replaced=false
  local i
  local diagnostics_playbook="${SYNTHRAN_PRIVATE_DIR:-}/ansible/playbooks/diagnostics.yml"
  local diagnostics_command=("${DEPLOYMENT_COMMAND[@]}")

  if [[ -z "${SYNTHRAN_PRIVATE_DIR:-}" || ! -f "$diagnostics_playbook" ]]; then
    echo "Failure diagnostics unavailable: staged diagnostics playbook is missing." >&2
    return 0
  fi

  for ((i = 0; i < ${#diagnostics_command[@]}; i++)); do
    case "${diagnostics_command[$i]}" in
      "$SYNTHRAN_PRIVATE_DIR"/ansible/playbooks/*.yml)
        diagnostics_command[$i]="$diagnostics_playbook"
        replaced=true
        break
        ;;
    esac
  done
  if [[ "$replaced" != true ]]; then
    echo "Failure diagnostics unavailable: deployment playbook argument was not found." >&2
    return 0
  fi

  echo "Collecting bounded deployment diagnostics after $reason."
  run_step "${diagnostics_command[@]}" </dev/null >>"$RUN_DIR/ansible.log" 2>&1 || diagnostics_rc=$?
  if (( diagnostics_rc != 0 )); then
    echo "Diagnostics collection was incomplete (status $diagnostics_rc); the original failure is preserved." >&2
  fi
  echo "Diagnostic artifacts: $RUN_DIR/diagnostics"
  return 0
}

if [[ -f "$RUN_DIR/source-revision.txt" ]]; then
  echo "Source revision: $(cat "$RUN_DIR/source-revision.txt")"
fi
ANSIBLE_RC=0
run_step "${DEPLOYMENT_COMMAND[@]}" </dev/null >"$RUN_DIR/ansible.log" 2>&1 || ANSIBLE_RC=$?
if (( ANSIBLE_RC != 0 )); then
  echo "Deployment provisioning failed with status $ANSIBLE_RC; complete Ansible output: $RUN_DIR/ansible.log" >&2
  collect_failure_diagnostics "provisioning failure"
  if [[ -f "$RUN_DIR/live-deployment-evidence.json" ]]; then
    echo "If the attested deployment and UE sessions remain healthy, resume with:" >&2
    echo "  ./deploy.sh --resume $RUN_DIR" >&2
  fi
  exit "$ANSIBLE_RC"
fi

if [[ "$WORKLOAD_ONLY" == true ]]; then
  echo "Reuse verification playbook completed; validating fresh live deployment evidence."
else
  echo "Provisioning playbook completed; validating fresh live deployment evidence."
fi

STATE_RC=0
if [[ "$WORKLOAD_ONLY" == true ]]; then
  run_step "$SYNTHRAN_PYTHON" -m synthran.deployment_state record-reuse \
    --candidate "$RUN_DIR/deployment-fingerprint.json" \
    --active "$ACTIVE_DEPLOYMENT_STATE" \
    --evidence "$RUN_DIR/live-deployment-evidence.json" || STATE_RC=$?
else
  run_step "$SYNTHRAN_PYTHON" -m synthran.deployment_state activate \
    --candidate "$RUN_DIR/deployment-fingerprint.json" \
    --active "$ACTIVE_DEPLOYMENT_STATE" \
    --evidence "$RUN_DIR/live-deployment-evidence.json" || STATE_RC=$?
fi
if (( STATE_RC != 0 )); then
  echo "Live deployment evidence was rejected with status $STATE_RC; deployment was not accepted." >&2
  collect_failure_diagnostics "live-evidence rejection"
  exit "$STATE_RC"
fi

echo "Live deployment evidence accepted."
HAS_EXPERIMENT=$("$SYNTHRAN_PYTHON" - "$CONFIG" <<'PY'
import sys
from synthran.scenario import load_scenario

print("true" if load_scenario(sys.argv[1]).get("experiment") else "false")
PY
)
if [[ "$HAS_EXPERIMENT" != true ]]; then
  echo "Testbed deployment completed; no experiment selected."
  exit 0
fi

echo "Running the selected experiment."
run_step "$SYNTHRAN_PYTHON" -m synthran.experiment run --config "$CONFIG" --run-dir "$RUN_DIR" \
  >>"$RUN_DIR/ansible.log" 2>&1
run_step "$SYNTHRAN_PYTHON" -m synthran.experiment finalize --config "$CONFIG" --run-dir "$RUN_DIR"
echo "Experiment run and finalization completed."
