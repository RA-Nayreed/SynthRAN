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
CHILD_PID=""
printf '%s\n' "$$" >"$RUN_DIR/controller.pid"

record_exit() {
  local status=$?
  trap - EXIT
  printf '%s\n' "$status" >"$RUN_DIR/controller-exit-code"
  echo "Deployment controller exited with status $status; artifacts retained in $RUN_DIR"
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

if [[ -f "$RUN_DIR/source-revision.txt" ]]; then
  echo "Source revision: $(cat "$RUN_DIR/source-revision.txt")"
fi
ANSIBLE_RC=0
run_step "$@" </dev/null >"$RUN_DIR/ansible.log" 2>&1 || ANSIBLE_RC=$?
if (( ANSIBLE_RC != 0 )); then
  echo "Deployment failed; complete Ansible output: $RUN_DIR/ansible.log" >&2
  if [[ -f "$RUN_DIR/live-deployment-evidence.json" ]]; then
    echo "If the attested deployment and UE sessions remain healthy, resume with:" >&2
    echo "  ./deploy.sh --resume $RUN_DIR" >&2
  fi
  exit "$ANSIBLE_RC"
fi

if [[ "$WORKLOAD_ONLY" == true ]]; then
  run_step "$SYNTHRAN_PYTHON" -m synthran.deployment_state record-reuse \
    --candidate "$RUN_DIR/deployment-fingerprint.json" \
    --active "$ACTIVE_DEPLOYMENT_STATE"
else
  run_step "$SYNTHRAN_PYTHON" -m synthran.deployment_state activate \
    --candidate "$RUN_DIR/deployment-fingerprint.json" \
    --active "$ACTIVE_DEPLOYMENT_STATE"
fi

echo "Running the selected experiment"
run_step "$SYNTHRAN_PYTHON" -m synthran.experiment run --config "$CONFIG" --run-dir "$RUN_DIR" \
  >>"$RUN_DIR/ansible.log" 2>&1
run_step "$SYNTHRAN_PYTHON" -m synthran.experiment finalize --config "$CONFIG" --run-dir "$RUN_DIR"
