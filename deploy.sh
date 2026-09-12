#!/usr/bin/env bash
set -euo pipefail

CONFIG="scenarios/reference.yml"; CONFIG_EXPLICIT=false; INTERACTIVE=false; NO_INPUT=false; NO_RESERVATION=false; DRY_RUN=false; VERBOSE=false; WORKLOAD_ONLY=false; RESUME=false; RESUME_FROM=""; PREPARED_WORKLOAD=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; CONFIG_EXPLICIT=true; shift 2 ;;
    -i|--interactive) INTERACTIVE=true; shift ;;
    -n|--no-input) NO_INPUT=true; shift ;;
    -r|--no-reservation) NO_RESERVATION=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    --prepared-workload) PREPARED_WORKLOAD="$2"; shift 2 ;;
    --workload-only) WORKLOAD_ONLY=true; NO_RESERVATION=true; shift ;;
    --resume) RESUME=true; RESUME_FROM="$2"; NO_RESERVATION=true; shift 2 ;;
    -v|--verbose) VERBOSE=true; shift ;;
    -h|--help)
      echo "Usage: ./deploy.sh [--config scenarios/<scenario>.yml] [--interactive] [--no-input] [--no-reservation] [--workload-only] [--prepared-workload path/to/bundle] [--resume results/<failed-run>] [--dry-run] [--verbose]"
      echo "Without options, deployment choices are prompted interactively. --interactive uses an explicit scenario as the prompt defaults. --workload-only reuses an already healthy matching 5G deployment. --resume safely continues an attested deployment that failed during the workload stage."
      exit 0
      ;;
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
  RESUME_SOURCE_MODEL="$RESUME_FROM/model"
  [[ -f "$RESUME_SOURCE_CONTRACT" ]] || { echo "Resume deployment identity not found: $RESUME_SOURCE_CONTRACT" >&2; exit 2; }
  [[ -f "$RESUME_SOURCE_EVIDENCE" ]] || { echo "Resume attestation evidence not found: $RESUME_SOURCE_EVIDENCE" >&2; exit 2; }
  [[ -f "$RESUME_SOURCE_MODEL/events.jsonl" ]] || { echo "Resume workload trace not found: $RESUME_SOURCE_MODEL/events.jsonl" >&2; exit 2; }
  CONFIG_EXPLICIT=true
else
  RESUME_SOURCE_CONTRACT=""
  RESUME_SOURCE_EVIDENCE=""
  RESUME_SOURCE_MODEL=""
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

# Load R2Lab access before inventory rendering, including --no-reservation runs.
if [[ -f .r2lab_config ]]; then
  # shellcheck disable=SC1091
  source .r2lab_config
fi
R2LAB_IDENTITY_FILE=${R2LAB_IDENTITY_FILE:-}
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

choose_sop_node() {
  local label="$1" default_node="$2" node_choice
  echo
  echo "Which node should host the ${label}? (default: ${default_node})"
  echo "1) sopnode-f1"
  echo "2) sopnode-f2"
  echo "3) sopnode-f3"
  echo "4) sopnode-w3"
  read -r -p "Enter choice [1-4]: " node_choice
  case "${node_choice:-}" in
    "") SELECTED_NODE="$default_node" ;;
    1) SELECTED_NODE=sopnode-f1 ;;
    2) SELECTED_NODE=sopnode-f2 ;;
    3) SELECTED_NODE=sopnode-f3 ;;
    4) SELECTED_NODE=sopnode-w3 ;;
    *) echo "Invalid node choice" >&2; exit 2 ;;
  esac
}

show_r2lab_matrix() {
  cat <<'MATRIX'

R2Lab resource matrix
---------------------
5G radio units selectable by SynthRAN
  1) n300      USRP N300, SophiaNode fiber, 2x2 antenna
  2) n320      USRP N320, SophiaNode fiber, 4x4 antenna
  3) benetel1  RAN550 O-RU, band n78, 4T4R, 100 MHz
  4) benetel2  RAN550 O-RU, band n78, 4T4R, 100 MHz

Physical 5G UEs are loaded from the selected 5G profile.
Availability and health are verified during reservation and provisioning.
MATRIX
}

profile_physical_ues() {
  "$SYNTHRAN_PYTHON" - "$1" <<'PY'
import sys, yaml
from pathlib import Path
profile = Path('deployment/group_vars/all') / f'5g_profile_{sys.argv[1]}.yaml'
if not profile.is_file():
    raise SystemExit(f'5G profile not found: {profile}')
data = yaml.safe_load(profile.read_text()) or {}
for name in (data.get('ues') or {}):
    if name.startswith(('qhat', 'qfit')):
        print(name)
PY
}

expand_r2lab_ue_selection() {
  "$SYNTHRAN_PYTHON" - "$1" "$2" <<'PY'
import sys, yaml
from pathlib import Path
profile = Path('deployment/group_vars/all') / f'5g_profile_{sys.argv[1]}.yaml'
data = yaml.safe_load(profile.read_text()) or {}
names = [name for name in (data.get('ues') or {}) if name.startswith(('qhat', 'qfit'))]
value = sys.argv[2].strip().lower()
chosen = []
for part in value.replace(' ', '').split(','):
    if part in names:
        selected = [part]
    else:
        bounds = part.split('-', 1)
        try:
            start, stop = int(bounds[0]), int(bounds[-1])
        except ValueError:
            raise SystemExit(f'Invalid physical UE selection: {part}')
        if start > stop or start < 1 or stop > len(names):
            raise SystemExit(f'Physical UE range must be ascending and within 1-{len(names)}: {part}')
        selected = names[start - 1:stop]
    for name in selected:
        if name not in chosen:
            chosen.append(name)
print(','.join(chosen))
PY
}

if ! $NO_INPUT && { ! $CONFIG_EXPLICIT || $INTERACTIVE; }; then
  [[ -t 0 ]] || { echo "Interactive input requires a terminal; use --config or --no-input" >&2; exit 2; }
  BASE_CONFIG="$CONFIG"
  mapfile -t SCENARIO_DEFAULTS < <("$SYNTHRAN_PYTHON" - "$BASE_CONFIG" <<'PY'
import sys, yaml
from pathlib import Path
d = yaml.safe_load(Path(sys.argv[1]).read_text())['deployment']
n = d.get('nodes', {}); r = d.get('reservation', {}); rr = d.get('r2lab_reservation', {})
values = [
    d.get('core','open5gs'), d.get('ran','srsran'), d.get('platform','rfsim'), d.get('ru','rfsim'),
    n.get('core','sopnode-f2'), n.get('ran','sopnode-f3'), n.get('broker',n.get('core','sopnode-f2')),
    d.get('profile','default'), ','.join(d.get('ues',[])), str(r.get('enabled',True)).lower(),
    str(r.get('duration_minutes',120)), r.get('image','ubuntu-jammy'), d.get('r2lab_username',''),
    str(rr.get('enabled',True)).lower(), str(rr.get('duration_minutes',120))
]
print('\n'.join(str(value) for value in values))
PY
  )
  DEFAULT_CORE=${SCENARIO_DEFAULTS[0]}; DEFAULT_RAN=${SCENARIO_DEFAULTS[1]}; DEFAULT_PLATFORM=${SCENARIO_DEFAULTS[2]}; DEFAULT_RU=${SCENARIO_DEFAULTS[3]}
  DEFAULT_CORE_NODE=${SCENARIO_DEFAULTS[4]}; DEFAULT_RAN_NODE=${SCENARIO_DEFAULTS[5]}; DEFAULT_BROKER_NODE=${SCENARIO_DEFAULTS[6]}; DEFAULT_PROFILE=${SCENARIO_DEFAULTS[7]}; DEFAULT_UES=${SCENARIO_DEFAULTS[8]}
  DEFAULT_RESERVE=${SCENARIO_DEFAULTS[9]}; DEFAULT_DURATION=${SCENARIO_DEFAULTS[10]}; DEFAULT_POS_IMAGE=${SCENARIO_DEFAULTS[11]}; DEFAULT_R2LAB_USERNAME=${SCENARIO_DEFAULTS[12]}
  DEFAULT_R2LAB_RESERVE=${SCENARIO_DEFAULTS[13]}; DEFAULT_R2LAB_DURATION=${SCENARIO_DEFAULTS[14]}

  echo
  printf '\033[1;36m'
  cat <<'BANNER'
  _____             _   _     _____            _   _
 / ____|           | | | |   |  __ \     /\   | \ | |
| (___  _   _ _ __ | |_| |__ | |__) |   /  \  |  \| |
 \___ \| | | | '_ \| __| '_ \|  _  /   / /\ \ | . ` |
 ____) | |_| | | | | |_| | | | | \ \  / ____ \| |\  |
|_____/ \__, |_| |_|\__|_| |_|_|  \_\/_/    \_\_| \_|
         __/ |
        |___/       Energy-aware 5G/6G deployment
BANNER
  printf '\033[0m'

  echo
  case "$DEFAULT_CORE" in oai) DEFAULT_CORE_CHOICE=1;; open5gs) DEFAULT_CORE_CHOICE=2;; free5gc) DEFAULT_CORE_CHOICE=3;; *) DEFAULT_CORE_CHOICE=2;; esac
  echo "Which CORE do you want to deploy? (default: $DEFAULT_CORE)"
  echo "1) OAI"
  echo "2) Open5GS"
  echo "3) Free5GC"
  read -r -p "Enter choice [1-3]: " CORE_CHOICE
  case "${CORE_CHOICE:-$DEFAULT_CORE_CHOICE}" in 1) SELECTED_CORE=oai;; 2) SELECTED_CORE=open5gs;; 3) SELECTED_CORE=free5gc;; *) echo "Invalid core choice" >&2; exit 2;; esac

  echo
  case "$DEFAULT_RAN" in oai) DEFAULT_RAN_CHOICE=1;; srsran) DEFAULT_RAN_CHOICE=2;; ueransim) DEFAULT_RAN_CHOICE=3;; *) DEFAULT_RAN_CHOICE=2;; esac
  echo "Which RAN do you want to deploy? (default: $DEFAULT_RAN)"
  echo "1) OAI"
  echo "2) srsRAN"
  echo "3) UERANSIM"
  read -r -p "Enter choice [1-3]: " RAN_CHOICE
  case "${RAN_CHOICE:-$DEFAULT_RAN_CHOICE}" in 1) SELECTED_RAN=oai;; 2) SELECTED_RAN=srsran;; 3) SELECTED_RAN=ueransim;; *) echo "Invalid RAN choice" >&2; exit 2;; esac

  echo
  [[ "$DEFAULT_PLATFORM" == r2lab ]] && DEFAULT_PLATFORM_CHOICE=2 || DEFAULT_PLATFORM_CHOICE=1
  echo "Which platform do you want to use? (default: $DEFAULT_PLATFORM)"
  echo "1) RFSIM"
  echo "2) R2Lab physical radio"
  read -r -p "Enter choice [1-2]: " PLATFORM_CHOICE
  case "${PLATFORM_CHOICE:-$DEFAULT_PLATFORM_CHOICE}" in 1) SELECTED_PLATFORM=rfsim; SELECTED_RU=rfsim;; 2) SELECTED_PLATFORM=r2lab;; *) echo "Invalid platform choice" >&2; exit 2;; esac
  if [[ "$SELECTED_PLATFORM" == r2lab && "$SELECTED_RAN" == ueransim ]]; then
    echo "UERANSIM is a software RAN and cannot drive an R2Lab physical radio" >&2
    exit 2
  fi

  if [[ "$SELECTED_PLATFORM" == r2lab ]]; then
    show_r2lab_matrix
    echo
    case "$DEFAULT_RU" in
      n300) DEFAULT_RU_CHOICE=1 ;;
      n320) DEFAULT_RU_CHOICE=2 ;;
      benetel1) DEFAULT_RU_CHOICE=3 ;;
      benetel2) DEFAULT_RU_CHOICE=4 ;;
      *) DEFAULT_RU=n300; DEFAULT_RU_CHOICE=1 ;;
    esac
    echo "Which radio unit do you want to use? (default: $DEFAULT_RU)"
    echo "1) n300"
    echo "2) n320"
    echo "3) benetel1"
    echo "4) benetel2"
    read -r -p "Enter choice [1-4]: " RU_CHOICE
    case "${RU_CHOICE:-$DEFAULT_RU_CHOICE}" in 1) SELECTED_RU=n300;; 2) SELECTED_RU=n320;; 3) SELECTED_RU=benetel1;; 4) SELECTED_RU=benetel2;; *) echo "Invalid RU choice" >&2; exit 2;; esac

    if [[ -f .r2lab_config ]]; then
      SELECTED_R2LAB_USERNAME=${R2LAB_USERNAME:-$DEFAULT_R2LAB_USERNAME}
      echo "Using saved R2Lab credentials for ${SELECTED_R2LAB_USERNAME:-unknown}"
    else
      read -r -p "R2Lab username (slice name) [$DEFAULT_R2LAB_USERNAME]: " SELECTED_R2LAB_USERNAME
      SELECTED_R2LAB_USERNAME=${SELECTED_R2LAB_USERNAME:-$DEFAULT_R2LAB_USERNAME}
      read -r -p "R2Lab account email: " R2LAB_EMAIL
      read -r -s -p "R2Lab password: " R2LAB_PASSWORD
      echo
      ( umask 077
        printf 'R2LAB_USERNAME=%q\nR2LAB_EMAIL=%q\nR2LAB_PASSWORD=%q\n' \
          "$SELECTED_R2LAB_USERNAME" "$R2LAB_EMAIL" "$R2LAB_PASSWORD" > .r2lab_config
      )
      export R2LAB_USERNAME="$SELECTED_R2LAB_USERNAME" R2LAB_EMAIL R2LAB_PASSWORD
    fi
    [[ -n "$SELECTED_R2LAB_USERNAME" ]] || { echo "R2Lab username is required" >&2; exit 2; }
    export R2LAB_USERNAME="$SELECTED_R2LAB_USERNAME"

    [[ "$DEFAULT_R2LAB_RESERVE" == true ]] && R2LAB_RESERVE_PROMPT="Y/n" || R2LAB_RESERVE_PROMPT="y/N"
    read -r -p "Reserve the R2Lab testbed? [$R2LAB_RESERVE_PROMPT]: " R2LAB_RESERVE_CHOICE
    SELECTED_R2LAB_RESERVE=$DEFAULT_R2LAB_RESERVE
    SELECTED_R2LAB_DURATION=$DEFAULT_R2LAB_DURATION
    [[ "${R2LAB_RESERVE_CHOICE:-}" =~ ^[Yy]$ ]] && SELECTED_R2LAB_RESERVE=true
    [[ "${R2LAB_RESERVE_CHOICE:-}" =~ ^[Nn]$ ]] && SELECTED_R2LAB_RESERVE=false
    if $SELECTED_R2LAB_RESERVE; then
      read -r -p "R2Lab reservation duration in minutes [$DEFAULT_R2LAB_DURATION]: " SELECTED_R2LAB_DURATION
      SELECTED_R2LAB_DURATION=${SELECTED_R2LAB_DURATION:-$DEFAULT_R2LAB_DURATION}
      [[ "$SELECTED_R2LAB_DURATION" =~ ^[1-9][0-9]*$ ]] || { echo "R2Lab duration must be a positive integer" >&2; exit 2; }
    fi
    echo "Auxiliary R2Lab sensor/edge/RF host roles from the old launcher are not available in the current deployment backend; skipping them."
  else
    SELECTED_R2LAB_USERNAME=""
    SELECTED_R2LAB_RESERVE=false
    SELECTED_R2LAB_DURATION=120
  fi

  choose_sop_node "core" "$DEFAULT_CORE_NODE"; SELECTED_CORE_NODE="$SELECTED_NODE"
  choose_sop_node "RAN" "$DEFAULT_RAN_NODE"; SELECTED_RAN_NODE="$SELECTED_NODE"
  SELECTED_BROKER_NODE="$SELECTED_CORE_NODE"
  read -r -p "5G profile [$DEFAULT_PROFILE]: " SELECTED_PROFILE
  SELECTED_PROFILE=${SELECTED_PROFILE:-$DEFAULT_PROFILE}
  [[ -f "deployment/group_vars/all/5g_profile_${SELECTED_PROFILE}.yaml" ]] || { echo "5G profile not found: $SELECTED_PROFILE" >&2; exit 2; }

  [[ "$DEFAULT_RESERVE" == true ]] && RESERVE_PROMPT="Y/n" || RESERVE_PROMPT="y/N"
  read -r -p "Ensure selected SOP nodes are reserved? [$RESERVE_PROMPT]: " RESERVE_CHOICE
  SELECTED_RESERVE=$DEFAULT_RESERVE
  [[ "${RESERVE_CHOICE:-}" =~ ^[Yy]$ ]] && SELECTED_RESERVE=true
  [[ "${RESERVE_CHOICE:-}" =~ ^[Nn]$ ]] && SELECTED_RESERVE=false
  if $SELECTED_RESERVE; then
    read -r -p "Reservation duration in minutes [$DEFAULT_DURATION]: " SELECTED_DURATION
    SELECTED_DURATION=${SELECTED_DURATION:-$DEFAULT_DURATION}
    [[ "$SELECTED_DURATION" =~ ^[1-9][0-9]*$ ]] || { echo "Duration must be a positive integer" >&2; exit 2; }
    read -r -p "POS image [$DEFAULT_POS_IMAGE]: " SELECTED_POS_IMAGE
    SELECTED_POS_IMAGE=${SELECTED_POS_IMAGE:-$DEFAULT_POS_IMAGE}
  fi
  SELECTED_DURATION=${SELECTED_DURATION:-$DEFAULT_DURATION}
  SELECTED_POS_IMAGE=${SELECTED_POS_IMAGE:-$DEFAULT_POS_IMAGE}

  if [[ "$SELECTED_PLATFORM" == rfsim ]]; then
    [[ "$DEFAULT_PLATFORM" == rfsim ]] || DEFAULT_UES="uesim01,uesim02"
    read -r -p "UEs, comma-separated [$DEFAULT_UES]: " SELECTED_UES
    SELECTED_UES=${SELECTED_UES:-$DEFAULT_UES}
  else
    mapfile -t PROFILE_PHYSICAL_UES < <(profile_physical_ues "$SELECTED_PROFILE")
    [[ ${#PROFILE_PHYSICAL_UES[@]} -gt 0 ]] || { echo "Selected profile has no supported physical R2Lab UEs" >&2; exit 2; }
    echo "Physical UEs available in profile $SELECTED_PROFILE:"
    for index in "${!PROFILE_PHYSICAL_UES[@]}"; do
      printf '  %2d) %s\n' "$((index + 1))" "${PROFILE_PHYSICAL_UES[$index]}"
    done
    if [[ "$DEFAULT_PLATFORM" != r2lab ]]; then DEFAULT_UES="${PROFILE_PHYSICAL_UES[0]}"; fi
    read -r -p "Physical UEs [$DEFAULT_UES]: " R2LAB_UE_INPUT
    [[ -z "$R2LAB_UE_INPUT" ]] && SELECTED_UES=$DEFAULT_UES || SELECTED_UES=$(expand_r2lab_ue_selection "$SELECTED_PROFILE" "$R2LAB_UE_INPUT")
    [[ -n "$SELECTED_UES" ]] || { echo "At least one physical UE is required" >&2; exit 2; }
  fi

  CONFIG="$RUN_DIR/interactive-scenario.yml"
  "$SYNTHRAN_PYTHON" - "$BASE_CONFIG" "$CONFIG" "$SELECTED_CORE" "$SELECTED_RAN" "$SELECTED_PLATFORM" "$SELECTED_RU" "$SELECTED_CORE_NODE" "$SELECTED_RAN_NODE" "$SELECTED_BROKER_NODE" "$SELECTED_PROFILE" "$SELECTED_UES" "$SELECTED_R2LAB_USERNAME" "$SELECTED_RESERVE" "$SELECTED_DURATION" "$SELECTED_POS_IMAGE" "$SELECTED_R2LAB_RESERVE" "$SELECTED_R2LAB_DURATION" <<'PY'
import sys, yaml
from pathlib import Path
source, output, core, ran, platform, ru, core_node, ran_node, broker_node, profile, ue_csv, r2lab_username, reserve, duration, pos_image, r2_reserve, r2_duration = sys.argv[1:]
scenario = yaml.safe_load(Path(source).read_text()) or {}
ues = [name.strip() for name in ue_csv.split(',') if name.strip()]
if not ues:
    raise SystemExit('At least one UE is required')
if platform == 'r2lab' and ran == 'ueransim':
    raise SystemExit('UERANSIM is a software RAN and cannot drive an R2Lab physical radio')
dep = scenario.setdefault('deployment', {})
host_vars = dep.get('host_vars', {})
dep.update({
    'core': core,
    'ran': ran,
    'platform': platform,
    'profile': profile,
    'ru': ru,
    'nodes': {'core': core_node, 'ran': ran_node, 'broker': broker_node},
    'ues': ues,
})
dep['host_vars'] = host_vars
dep['reservation'] = {'enabled': reserve == 'true', 'duration_minutes': int(duration), 'image': pos_image}
dep['r2lab_reservation'] = {'enabled': r2_reserve == 'true', 'duration_minutes': int(r2_duration)}
dep.pop('r2lab_experiment_nodes', None)
if r2lab_username:
    dep['r2lab_username'] = r2lab_username
Path(output).write_text(yaml.safe_dump(scenario, sort_keys=False))
PY

  # The experiment owns sensor-to-UE remapping now. The generic dispatcher
  # resolves experiment.config and passes it to the current experiment runner.
  "$SYNTHRAN_PYTHON" -m synthran.experiment configure --config "$CONFIG"

  echo
  echo "Deployment summary"
  echo "  Core:     $SELECTED_CORE on $SELECTED_CORE_NODE"
  echo "  RAN:      $SELECTED_RAN on $SELECTED_RAN_NODE"
  echo "  Platform: $SELECTED_PLATFORM ($SELECTED_RU)"
  echo "  UEs:      $SELECTED_UES"
  echo "  Profile:  $SELECTED_PROFILE"
  echo "  POS:      $SELECTED_RESERVE, ${SELECTED_DURATION}m, image $SELECTED_POS_IMAGE"
  [[ "$SELECTED_PLATFORM" == r2lab ]] && echo "  R2Lab:    $SELECTED_R2LAB_RESERVE, ${SELECTED_R2LAB_DURATION}m"
  read -r -p "Continue? [Y/n]: " CONFIRM_DEPLOY
  [[ ! "${CONFIRM_DEPLOY:-y}" =~ ^[Nn]$ ]] || exit 0
fi

SOURCE_CONFIG="$CONFIG"
PUBLIC_CONFIG="$RUN_DIR/resolved-scenario.yml"
CONFIG="$PRIVATE_RUN_DIR/resolved-scenario.yml"
"$SYNTHRAN_PYTHON" -m synthran.deployment_state resolve \
  --source "$SOURCE_CONFIG" --output "$CONFIG"

write_public_scenario() {
  "$SYNTHRAN_PYTHON" - "$CONFIG" "$PUBLIC_CONFIG" <<'PY'
import sys, yaml
from pathlib import Path
from synthran.scenario import redacted
source, output = map(Path, sys.argv[1:3])
data = yaml.safe_load(source.read_text()) or {}
output.write_text(yaml.safe_dump(redacted(data), sort_keys=False))
PY
}
write_public_scenario

HAS_EXPERIMENT=$("$SYNTHRAN_PYTHON" - "$CONFIG" <<'PY'
import sys, yaml
value = yaml.safe_load(open(sys.argv[1])) or {}
print('true' if value.get('experiment') else 'false')
PY
)
if [[ "$HAS_EXPERIMENT" == true ]]; then
  deployment_section "Preparing the selected experiment"
fi
EXPERIMENT_PREPARE=("$SYNTHRAN_PYTHON" -m synthran.experiment prepare --config "$CONFIG" --run-dir "$RUN_DIR")
if [[ -n "$PREPARED_WORKLOAD" ]]; then EXPERIMENT_PREPARE+=(--prepared-workload "$PREPARED_WORKLOAD"); fi
if $RESUME; then EXPERIMENT_PREPARE+=(--resume-from "$RESUME_FROM"); fi
"${EXPERIMENT_PREPARE[@]}"
write_public_scenario

if ! $WORKLOAD_ONLY && ! $RESUME && ! $DRY_RUN; then
  "$SYNTHRAN_PYTHON" -m synthran.deployment_state invalidate \
    --active "$ACTIVE_DEPLOYMENT_STATE" --run-id "$RUN_ID"
fi

if ! $NO_RESERVATION && ! $DRY_RUN; then
  deployment_section "Resolving the SOP reservation"
  command -v pos >/dev/null || { echo "POS reservation requested but the pos command is unavailable" >&2; exit 1; }
  "$SYNTHRAN_PYTHON" deployment/scripts/reserve_sop.py "$CONFIG" "$RUN_DIR"
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
from synthran.r2lab import access
d = yaml.safe_load(open(sys.argv[1]))['deployment']
r = d.get('r2lab_reservation', {})
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
  [[ -n "${R2LAB_USERNAME:-}" ]] || { echo "R2Lab username must be set in .r2lab_config or the scenario" >&2; exit 1; }

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
[[ -x "$ANSIBLE_GALAXY" && -x "$ANSIBLE_PLAYBOOK" ]] || { echo "The isolated Ansible runtime was not installed correctly" >&2; exit 1; }
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
if $VERBOSE; then ANSIBLE_COMMAND+=(--verbose); fi

exec bash deployment/scripts/run_deployment.sh \
  "$RUN_DIR" "$SYNTHRAN_PYTHON" "$CONFIG" "$ACTIVE_DEPLOYMENT_STATE" \
  "$WORKLOAD_ONLY" "${ANSIBLE_COMMAND[@]}"
