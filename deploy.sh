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
  RESUME_ID="$(basename -- "$RESUME_FROM")"
  PRIVATE_RESUME_CONFIG="$PWD/.synthran/execution/$RESUME_ID/resolved-scenario.yml"
  if [[ -f "$PRIVATE_RESUME_CONFIG" ]]; then
    CONFIG="$PRIVATE_RESUME_CONFIG"
  else
    CONFIG="$RESUME_FROM/resolved-scenario.yml"
  fi
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
RUN_ID="$(date -u +%Y%m%dT%H%M%S%NZ)"
RUN_DIR="results/$RUN_ID"
PRIVATE_RUN_DIR="$PWD/.synthran/execution/$RUN_ID"
mkdir -p "$RUN_DIR"
install -d -m 0700 "$PRIVATE_RUN_DIR"
export SYNTHRAN_PRIVATE_DIR="$PRIVATE_RUN_DIR"
git rev-parse HEAD >"$RUN_DIR/source-revision.txt" 2>/dev/null || printf 'unknown\n' >"$RUN_DIR/source-revision.txt"
ACTIVE_DEPLOYMENT_STATE="$PWD/.synthran/deployment-fingerprint.json"
mkdir -p .synthran .synthran/r2lab
R2LAB_FARADAY_KNOWN_HOSTS=${R2LAB_FARADAY_KNOWN_HOSTS:-$PWD/.synthran/r2lab/faraday_known_hosts}
export R2LAB_FARADAY_KNOWN_HOSTS
# Load R2Lab access before rendering inventory, including --no-reservation runs.
if [[ -f .r2lab_config ]]; then
  source .r2lab_config
fi
R2LAB_IDENTITY_FILE=${R2LAB_IDENTITY_FILE:-}
# Preserve the proven Duckburg R2Lab identity fallback used before the refactor.
if [[ -z "$R2LAB_IDENTITY_FILE" && -r "$HOME/.ssh/id_rsa_r2lab_duckburg" ]]; then
  R2LAB_IDENTITY_FILE="$HOME/.ssh/id_rsa_r2lab_duckburg"
fi
if [[ -n "$R2LAB_IDENTITY_FILE" ]]; then
  [[ -r "$R2LAB_IDENTITY_FILE" ]] || { echo "R2Lab SSH identity is not readable: $R2LAB_IDENTITY_FILE" >&2; exit 1; }
fi
export R2LAB_USERNAME="${R2LAB_USERNAME:-}" R2LAB_IDENTITY_FILE
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
"$SYNTHRAN_PYTHON" -m synthran.runtime deployment --log "$RUN_DIR/bootstrap.log"

if ! $NO_INPUT && { ! $CONFIG_EXPLICIT || $INTERACTIVE; }; then
  [[ -t 0 ]] || { echo "Interactive input requires a terminal; use --config or --no-input" >&2; exit 2; }
  "$SYNTHRAN_PYTHON" -m synthran.configure --source "$CONFIG" --output "$PRIVATE_RUN_DIR/selected-scenario.yml"
  CONFIG="$PRIVATE_RUN_DIR/selected-scenario.yml"
fi

SOURCE_CONFIG="$CONFIG"
PUBLIC_CONFIG="$RUN_DIR/resolved-scenario.yml"
CONFIG="$PRIVATE_RUN_DIR/resolved-scenario.yml"
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
write_public_scenario() {
  "$SYNTHRAN_PYTHON" - "$CONFIG" "$PUBLIC_CONFIG" <<'PYCONFIG'
import sys, yaml
from pathlib import Path
from synthran.scenario import redacted
source, output = map(Path, sys.argv[1:3])
data = yaml.safe_load(source.read_text()) or {}
output.write_text(yaml.safe_dump(redacted(data), sort_keys=False))
PYCONFIG
}
write_public_scenario

deployment_section "Preparing the selected experiment"
"$SYNTHRAN_PYTHON" -m synthran.experiment prepare --config "$CONFIG" --run-dir "$RUN_DIR" \
  --prepared-workload "$PREPARED_WORKLOAD" --resume-from "$RESUME_FROM"
write_public_scenario
if ! $WORKLOAD_ONLY && ! $RESUME && ! $DRY_RUN; then
  "$SYNTHRAN_PYTHON" -m synthran.deployment_state invalidate \
    --active "$ACTIVE_DEPLOYMENT_STATE" --run-id "$RUN_ID"
fi

if ! $NO_RESERVATION && ! $DRY_RUN; then
  deployment_section "Resolving the SOP reservation"
  command -v pos >/dev/null || { echo "POS reservation requested but the pos command is unavailable" >&2; exit 1; }
  "$SYNTHRAN_PYTHON" deployment/scripts/reserve_sop.py "$CONFIG" "$RUN_DIR"
  # The reservation helper may replace SOP nodes. Re-publish the redacted
  # canonical scenario after that decision so inventory and public evidence agree.
  write_public_scenario
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
  [[ -n "${R2LAB_USERNAME:-}" ]] || {
    echo "R2Lab username must be set in .r2lab_config or the scenario" >&2
    exit 1
  }

  # R2Lab/Faraday uses Europe/Paris local lease coordinates. Keep the provider
  # clock explicit instead of inheriting the controller host timezone.
  R2LAB_CLOCK=$(TZ=Europe/Paris date +'%H%M')
  R2LAB_START="$(TZ=Europe/Paris date +'%Y-%m-%dT')${R2LAB_CLOCK:0:2}:${R2LAB_CLOCK:2:1}0"
  R2LAB_START_EPOCH=$(TZ=Europe/Paris date -d "$R2LAB_START" +%s)
  R2LAB_END_EPOCH=$((R2LAB_START_EPOCH + R2LAB_DURATION * 60))

  if [[ -f "$RUN_DIR/pos-selection.json" ]]; then
    POS_COVERAGE_END=$("$SYNTHRAN_PYTHON" - "$RUN_DIR/pos-selection.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1]))
print(value.get('coverage_end', ''))
PY
)
    if [[ -n "$POS_COVERAGE_END" ]]; then
      POS_COVERAGE_END_EPOCH=$(date -d "$POS_COVERAGE_END" +%s)
      if (( POS_COVERAGE_END_EPOCH <= R2LAB_START_EPOCH )); then
        echo "Accepted SOP reservation ends before the R2Lab deployment window starts" >&2
        exit 1
      fi
      if (( POS_COVERAGE_END_EPOCH < R2LAB_END_EPOCH )); then
        R2LAB_END_EPOCH=$POS_COVERAGE_END_EPOCH
        echo "Capping R2Lab coverage at the accepted SOP reservation end: $POS_COVERAGE_END"
      fi
    fi
  fi

  R2LAB_END=$(TZ=Europe/Paris date -d "@$R2LAB_END_EPOCH" +'%Y-%m-%dT%H:%M')
  echo "Resolving provider-backed R2Lab coverage for $R2LAB_START to $R2LAB_END"
  if ! printf '%s\n' "${R2LAB_PASSWORD:-}" | \
    "$SYNTHRAN_PYTHON" deployment/scripts/reserve_r2lab.py \
      --host "$R2LAB_HOST" \
      --username "$R2LAB_USERNAME" \
      --identity-file "$R2LAB_IDENTITY_FILE" \
      --known-hosts "$R2LAB_FARADAY_KNOWN_HOSTS" \
      --email "${R2LAB_EMAIL:-}" \
      --start "$R2LAB_START" \
      --end "$R2LAB_END" \
      --output "$RUN_DIR/r2lab-lease.json" \
      --log "$RUN_DIR/r2lab-reservation.log"; then
    echo "R2Lab reservation/coverage verification failed; the separate SOP allocation was left intact" >&2
    exit 1
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
  DEPLOYMENT_PLAYBOOK="$PRIVATE_RUN_DIR/ansible/playbooks/workload.yml"
  echo "The stored deployment identity will be checked before running the experiment"
elif $RESUME; then
  DEPLOYMENT_PLAYBOOK="$PRIVATE_RUN_DIR/ansible/playbooks/resume.yml"
  echo "The failed run's live attestation will be checked before its workload is resumed"
else
  DEPLOYMENT_PLAYBOOK="$PRIVATE_RUN_DIR/ansible/playbooks/site.yml"
fi
ANSIBLE_COMMAND=("$ANSIBLE_PLAYBOOK" -i "$PRIVATE_RUN_DIR/inventory.yml"
  -e "@deployment/group_vars/all/all.yml"
  -e "@$PRIVATE_RUN_DIR/deployment-vars.yml"
  "$DEPLOYMENT_PLAYBOOK")
if $VERBOSE; then
  ANSIBLE_COMMAND+=(--verbose)
fi
exec bash deployment/scripts/run_deployment.sh \
  "$RUN_DIR" "$SYNTHRAN_PYTHON" "$CONFIG" "$ACTIVE_DEPLOYMENT_STATE" \
  "$WORKLOAD_ONLY" "${ANSIBLE_COMMAND[@]}"
