#!/usr/bin/env bash
set -euo pipefail

CONFIG="scenarios/reference.yml"; CONFIG_EXPLICIT=false; INTERACTIVE=false; NO_INPUT=false; NO_RESERVATION=false; DRY_RUN=false; VERBOSE=false; WORKLOAD_ONLY=false; RESUME=false; RESUME_FROM=""; PREPARED_WORKLOAD=""; TESTBED_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; CONFIG_EXPLICIT=true; shift 2 ;;
    -i|--interactive) INTERACTIVE=true; shift ;;
    -n|--no-input) NO_INPUT=true; shift ;;
    -r|--no-reservation) NO_RESERVATION=true; shift ;;
    --testbed-only) TESTBED_ONLY=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --prepared-workload) PREPARED_WORKLOAD="$2"; shift 2 ;;
    --workload-only) WORKLOAD_ONLY=true; NO_RESERVATION=true; shift ;;
    --resume) RESUME=true; RESUME_FROM="$2"; NO_RESERVATION=true; shift 2 ;;
    -v|--verbose) VERBOSE=true; shift ;;
    -h|--help) echo "Usage: ./deploy.sh [--config scenarios/<scenario>.yml] [--interactive] [--no-input] [--no-reservation] [--workload-only] [--prepared-workload path/to/bundle] [--resume results/<failed-run>] [--testbed-only] [--dry-run] [--verbose]"; echo "Without options, deployment choices are prompted interactively. --interactive uses an explicit scenario as the prompt defaults. --workload-only reuses an already healthy matching 5G deployment. --resume safely continues an attested deployment that failed during the workload stage."; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
if $INTERACTIVE && $NO_INPUT; then echo "--interactive and --no-input cannot be used together" >&2; exit 2; fi
if [[ -n "$PREPARED_WORKLOAD" ]] && { $RESUME || $INTERACTIVE || ! $CONFIG_EXPLICIT; }; then
  echo "--prepared-workload requires --config and cannot be combined with --resume or --interactive" >&2
  exit 2
fi
if $RESUME && $WORKLOAD_ONLY; then echo "--resume and --workload-only cannot be combined" >&2; exit 2; fi
if $RESUME && $INTERACTIVE; then echo "--resume cannot be combined with --interactive" >&2; exit 2; fi
if $RESUME && $DRY_RUN; then echo "--resume cannot be combined with --dry-run" >&2; exit 2; fi
if $RESUME && $CONFIG_EXPLICIT; then echo "--resume uses the failed run's resolved scenario and cannot be combined with --config" >&2; exit 2; fi
if $WORKLOAD_ONLY && $INTERACTIVE; then echo "--workload-only requires a fixed scenario and cannot be interactive" >&2; exit 2; fi
if $WORKLOAD_ONLY && ! $CONFIG_EXPLICIT; then echo "--workload-only requires --config so the reused deployment can be validated against an explicit scenario" >&2; exit 2; fi
if $RESUME; then
  [[ -d "$RESUME_FROM" ]] || { echo "Resume run directory not found: $RESUME_FROM" >&2; exit 2; }
  CONFIG="$RESUME_FROM/resolved-scenario.yml"
  RESUME_SOURCE_CONTRACT="$RESUME_FROM/deployment-fingerprint.json"
  RESUME_SOURCE_EVIDENCE="$RESUME_FROM/live-deployment-evidence.json"
  [[ -f "$RESUME_SOURCE_CONTRACT" ]] || { echo "Resume deployment identity not found: $RESUME_SOURCE_CONTRACT" >&2; exit 2; }
  [[ -f "$RESUME_SOURCE_EVIDENCE" ]] || { echo "Resume attestation evidence not found: $RESUME_SOURCE_EVIDENCE" >&2; exit 2; }
  CONFIG_EXPLICIT=true
else
  RESUME_SOURCE_CONTRACT=""
  RESUME_SOURCE_EVIDENCE=""
fi
[[ -f "$CONFIG" ]] || { echo "Scenario not found: $CONFIG" >&2; exit 2; }
RUN_ID="$(date -u +%Y%m%dT%H%M%S%NZ)"; RUN_DIR="results/$RUN_ID"; mkdir -p "$RUN_DIR"
git rev-parse HEAD >"$RUN_DIR/source-revision.txt" 2>/dev/null || printf 'unknown\n' >"$RUN_DIR/source-revision.txt"
ACTIVE_DEPLOYMENT_STATE="$PWD/.synthran/deployment-fingerprint.json"
mkdir -p .synthran
# Load R2Lab access before rendering inventory, including --no-reservation runs.
if [[ -f .r2lab_config ]]; then
  source .r2lab_config
fi
export R2LAB_USERNAME="${R2LAB_USERNAME:-}" R2LAB_IDENTITY_FILE="${R2LAB_IDENTITY_FILE:-}"
command -v flock >/dev/null || { echo "flock is required to protect deployments from overlapping runs" >&2; exit 1; }
exec 9>.synthran/deploy.lock
if ! flock -n 9; then
  echo "Another SynthRAN deployment is still running. Stop it before starting a new deployment." >&2
  echo "Inspect it with: pgrep -af 'deploy.sh|ansible-playbook|prepare-demo-oai'" >&2
  exit 1
fi
printf '%s\n' "$$" 1>&9
deployment_section() {
  echo
  echo "$1"
  printf '%*s\n' "${#1}" '' | tr ' ' '-'
}
if [[ -x .venv/bin/python ]]; then
  SYNTHRAN_PYTHON=.venv/bin/python
else
  command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
  python3 -m venv .venv
  SYNTHRAN_PYTHON=.venv/bin/python
fi
deployment_section "Preparing the local SynthRAN runtime"
if ! "$SYNTHRAN_PYTHON" -m pip install --disable-pip-version-check -e '.[deployment]' >"$RUN_DIR/bootstrap.log" 2>&1; then
  cat "$RUN_DIR/bootstrap.log" >&2
  echo "Runtime preparation failed; full output: $RUN_DIR/bootstrap.log" >&2
  exit 1
fi

if ! $NO_INPUT && { ! $CONFIG_EXPLICIT || $INTERACTIVE; }; then
  [[ -t 0 ]] || { echo "Interactive input requires a terminal; use --config or --no-input" >&2; exit 2; }
  "$SYNTHRAN_PYTHON" -m synthran.configure --source "$CONFIG" --output "$RUN_DIR/selected-scenario.yml"
  CONFIG="$RUN_DIR/selected-scenario.yml"
fi

SOURCE_CONFIG="$CONFIG"
CONFIG="$RUN_DIR/resolved-scenario.yml"
"$SYNTHRAN_PYTHON" -m synthran.deployment_state resolve \
  --source "$SOURCE_CONFIG" --output "$CONFIG"
if $TESTBED_ONLY; then
  "$SYNTHRAN_PYTHON" - "$CONFIG" <<'PYCONFIG'
import sys, yaml
from pathlib import Path
p = Path(sys.argv[1]); data = yaml.safe_load(p.read_text())
data.pop('experiment', None)
p.write_text(yaml.safe_dump(data, sort_keys=False))
PYCONFIG
fi
deployment_section "Preparing the selected experiment"
"$SYNTHRAN_PYTHON" -m synthran.experiment prepare --config "$CONFIG" --run-dir "$RUN_DIR" \
  --prepared-workload "$PREPARED_WORKLOAD" --resume-from "$RESUME_FROM"
if ! $WORKLOAD_ONLY && ! $RESUME && ! $DRY_RUN; then
  "$SYNTHRAN_PYTHON" -m synthran.deployment_state invalidate \
    --active "$ACTIVE_DEPLOYMENT_STATE" --run-id "$RUN_ID"
fi

if ! $NO_RESERVATION && ! $DRY_RUN; then
  deployment_section "Resolving the SOP reservation"
  command -v pos >/dev/null || { echo "POS reservation requested but the pos command is unavailable" >&2; exit 1; }
  "$SYNTHRAN_PYTHON" deployment/scripts/reserve_sop.py "$CONFIG" "$RUN_DIR"
fi

REUSE_EXISTING=false
if $WORKLOAD_ONLY || $RESUME; then REUSE_EXISTING=true; fi
"$SYNTHRAN_PYTHON" -m synthran.inventory "$CONFIG" "$RUN_DIR" "$REUSE_EXISTING" "$RESUME_SOURCE_CONTRACT"

if $DRY_RUN; then echo "Prepared $RUN_DIR; deployment skipped"; exit 0; fi

if $WORKLOAD_ONLY; then
  "$SYNTHRAN_PYTHON" -m synthran.deployment_state verify-reuse \
    --candidate "$RUN_DIR/deployment-fingerprint.json" \
    --active "$ACTIVE_DEPLOYMENT_STATE"
fi
if $RESUME; then
  "$SYNTHRAN_PYTHON" -m synthran.deployment_state verify-resume \
    --source "$RESUME_SOURCE_CONTRACT" \
    --candidate "$RUN_DIR/deployment-fingerprint.json" \
    --evidence "$RESUME_SOURCE_EVIDENCE"
fi

mapfile -t R2LAB_SETTINGS < <("$SYNTHRAN_PYTHON" - "$CONFIG" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))['deployment']
r = d.get('r2lab_reservation', {})
from synthran.r2lab import access
a = access(d)
print(d.get('platform', 'rfsim'))
print('true' if r.get('enabled', True) else 'false')
print(int(r.get('duration_minutes', 120)))
print(a['host'])
print(a['username'])
print(a['identity_file'])
PY
)
if [[ "${R2LAB_SETTINGS[0]}" == r2lab && "${R2LAB_SETTINGS[1]}" == true && "$NO_RESERVATION" == false ]]; then
  deployment_section "Preparing the R2Lab reservation"
  R2LAB_DURATION=${R2LAB_SETTINGS[2]}
  R2LAB_HOST=${R2LAB_SETTINGS[3]}
  R2LAB_USERNAME=${R2LAB_SETTINGS[4]}
  R2LAB_IDENTITY_FILE=${R2LAB_SETTINGS[5]}
  [[ -n "${R2LAB_USERNAME:-}" && -n "${R2LAB_EMAIL:-}" && -n "${R2LAB_PASSWORD:-}" ]] || {
    echo "R2Lab username, email, and password must all be set in .r2lab_config" >&2
    exit 1
  }
  R2LAB_CLOCK=$(date +'%H%M')
  R2LAB_START="$(date +'%Y-%m-%dT')${R2LAB_CLOCK:0:2}:${R2LAB_CLOCK:2:1}0"
  R2LAB_START_EPOCH=$(date -d "$R2LAB_START" +%s)
  R2LAB_END=$(date -d "@$((R2LAB_START_EPOCH + R2LAB_DURATION * 60))" +'%Y-%m-%dT%H:%M')
  printf -v R2LAB_REMOTE_COMMAND 'rhubarbe book %q %q -e %q -p %q -s %q -v' \
    "$R2LAB_START" "$R2LAB_END" "$R2LAB_EMAIL" "$R2LAB_PASSWORD" "$R2LAB_USERNAME"
  echo "Resolving R2Lab access for $R2LAB_START to $R2LAB_END"
  R2LAB_SSH=(ssh)
  if [[ -n "${R2LAB_IDENTITY_FILE:-}" ]]; then
    R2LAB_SSH+=(-i "$R2LAB_IDENTITY_FILE" -o IdentitiesOnly=yes)
    echo "Using R2Lab SSH identity: $R2LAB_IDENTITY_FILE"
  fi
  echo "Checking SSH access to $R2LAB_USERNAME@$R2LAB_HOST"
  if ! "${R2LAB_SSH[@]}" -o BatchMode=yes -o ConnectTimeout=15 \
    "$R2LAB_USERNAME@$R2LAB_HOST" true; then
    echo "R2Lab SSH authentication failed; no reservation was attempted" >&2
    exit 1
  fi
  R2LAB_LEASE_CHECK=$("${R2LAB_SSH[@]}" "$R2LAB_USERNAME@$R2LAB_HOST" \
    "rhubarbe leases --check" 2>&1) && R2LAB_LEASE_ACTIVE=true || R2LAB_LEASE_ACTIVE=false
  if $R2LAB_LEASE_ACTIVE; then
    printf '%s\n' "$R2LAB_LEASE_CHECK" | tee "$RUN_DIR/r2lab-reservation.log"
    echo "Reusing the active R2Lab lease owned by $R2LAB_USERNAME"
  else
    echo "No active owned R2Lab lease was found; requesting a new lease"
    if ! "${R2LAB_SSH[@]}" "$R2LAB_USERNAME@$R2LAB_HOST" "$R2LAB_REMOTE_COMMAND" \
    2>&1 | tee "$RUN_DIR/r2lab-reservation.log"; then
      echo "R2Lab reservation failed; the separate SOP allocation was left intact" >&2
      exit 1
    fi
  fi
fi

deployment_section "Preparing Ansible dependencies"
ANSIBLE_GALAXY="$PWD/.venv/bin/ansible-galaxy"
ANSIBLE_PLAYBOOK="$PWD/.venv/bin/ansible-playbook"
[[ -x "$ANSIBLE_GALAXY" && -x "$ANSIBLE_PLAYBOOK" ]] || {
  echo "The isolated Ansible runtime was not installed correctly" >&2
  exit 1
}
if ! "$ANSIBLE_GALAXY" collection install -r deployment/collections/requirements.yml >"$RUN_DIR/ansible-galaxy.log" 2>&1; then
  cat "$RUN_DIR/ansible-galaxy.log" >&2
  echo "Ansible dependency preparation failed; full output: $RUN_DIR/ansible-galaxy.log" >&2
  exit 1
fi

if $WORKLOAD_ONLY || $RESUME; then
  deployment_section "Reusing the existing 5G stack"
else
  deployment_section "Provisioning nodes and deploying the selected 5G stack"
fi
export ANSIBLE_ROLES_PATH="$PWD/deployment/roles"
export ANSIBLE_CONFIG="$PWD/deployment/ansible.cfg"
export ANSIBLE_FORCE_COLOR=0
export PYTHONUNBUFFERED=1
if $WORKLOAD_ONLY; then
  DEPLOYMENT_PLAYBOOK="$RUN_DIR/ansible/playbooks/workload.yml"
  echo "The stored deployment identity will be checked before running the experiment"
elif $RESUME; then
  DEPLOYMENT_PLAYBOOK="$RUN_DIR/ansible/playbooks/resume.yml"
  echo "The failed run's live attestation will be checked before its workload is resumed"
else
  DEPLOYMENT_PLAYBOOK="$RUN_DIR/ansible/playbooks/site.yml"
fi
ANSIBLE_COMMAND=("$ANSIBLE_PLAYBOOK" -i "$RUN_DIR/inventory.yml"
  -e "@deployment/group_vars/all/all.yml"
  -e "@$RUN_DIR/deployment-vars.yml"
  "$DEPLOYMENT_PLAYBOOK")
if $VERBOSE; then
  ANSIBLE_COMMAND+=(--verbose)
fi
exec bash deployment/scripts/run_deployment.sh \
  "$RUN_DIR" "$SYNTHRAN_PYTHON" "$CONFIG" "$ACTIVE_DEPLOYMENT_STATE" \
  "$WORKLOAD_ONLY" "${ANSIBLE_COMMAND[@]}"
