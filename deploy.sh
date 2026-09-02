#!/usr/bin/env bash
set -euo pipefail

CONFIG="scenarios/reference.yml"; CONFIG_EXPLICIT=false; NO_INPUT=false; NO_RESERVATION=false; DRY_RUN=false; VERBOSE=false; SOP_RESERVATION_DONE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; CONFIG_EXPLICIT=true; shift 2 ;;
    -n|--no-input) NO_INPUT=true; shift ;;
    -r|--no-reservation) NO_RESERVATION=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    -v|--verbose) VERBOSE=true; shift ;;
    -h|--help) echo "Usage: ./deploy.sh [--config scenarios/<scenario>.yml] [--no-input] [--no-reservation] [--dry-run] [--verbose]"; echo "Without options, deployment choices are prompted interactively."; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ -f "$CONFIG" ]] || { echo "Scenario not found: $CONFIG" >&2; exit 2; }
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"; RUN_DIR="results/$RUN_ID"; mkdir -p "$RUN_DIR"
R2LAB_IDENTITY_FILE=${R2LAB_IDENTITY_FILE:-}
if [[ -z "$R2LAB_IDENTITY_FILE" && -r "$HOME/.ssh/id_rsa_r2lab_duckburg" ]]; then
  R2LAB_IDENTITY_FILE="$HOME/.ssh/id_rsa_r2lab_duckburg"
fi
if [[ -n "$R2LAB_IDENTITY_FILE" ]]; then
  [[ -r "$R2LAB_IDENTITY_FILE" ]] || { echo "R2Lab SSH identity is not readable: $R2LAB_IDENTITY_FILE" >&2; exit 1; }
  export R2LAB_IDENTITY_FILE
fi
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
if ! "$SYNTHRAN_PYTHON" -m pip install --disable-pip-version-check -e . >"$RUN_DIR/bootstrap.log" 2>&1; then
  cat "$RUN_DIR/bootstrap.log" >&2
  echo "Runtime preparation failed; full output: $RUN_DIR/bootstrap.log" >&2
  exit 1
fi

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

if ! $CONFIG_EXPLICIT && ! $NO_INPUT; then
  [[ -t 0 ]] || { echo "Interactive input requires a terminal; use --config or --no-input" >&2; exit 2; }
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
  echo "Which CORE do you want to deploy? (default: Open5GS)"
  echo "1) OAI"
  echo "2) Open5GS"
  echo "3) Free5GC"
  read -r -p "Enter choice [1-3]: " CORE_CHOICE
  case "${CORE_CHOICE:-2}" in 1) SELECTED_CORE=oai;; 2) SELECTED_CORE=open5gs;; 3) SELECTED_CORE=free5gc;; *) echo "Invalid core choice" >&2; exit 2;; esac

  echo
  echo "Which RAN do you want to deploy? (default: srsRAN)"
  echo "1) OAI"
  echo "2) srsRAN"
  echo "3) UERANSIM"
  read -r -p "Enter choice [1-3]: " RAN_CHOICE
  case "${RAN_CHOICE:-2}" in 1) SELECTED_RAN=oai;; 2) SELECTED_RAN=srsran;; 3) SELECTED_RAN=ueransim;; *) echo "Invalid RAN choice" >&2; exit 2;; esac

  echo
  echo "Which platform do you want to use? (default: RFSIM)"
  echo "1) RFSIM"
  echo "2) R2Lab physical radio"
  read -r -p "Enter choice [1-2]: " PLATFORM_CHOICE
  case "${PLATFORM_CHOICE:-1}" in 1) SELECTED_PLATFORM=rfsim; SELECTED_RU=rfsim;; 2) SELECTED_PLATFORM=r2lab;; *) echo "Invalid platform choice" >&2; exit 2;; esac

  if [[ "$SELECTED_PLATFORM" == r2lab ]]; then
    echo
    echo "Which radio unit do you want to use? (default: n300)"
    echo "1) n300"
    echo "2) n320"
    echo "3) benetel1"
    echo "4) benetel2"
    read -r -p "Enter choice [1-4]: " RU_CHOICE
    case "${RU_CHOICE:-1}" in 1) SELECTED_RU=n300;; 2) SELECTED_RU=n320;; 3) SELECTED_RU=benetel1;; 4) SELECTED_RU=benetel2;; *) echo "Invalid RU choice" >&2; exit 2;; esac
    if [[ -f .r2lab_config ]]; then
      # shellcheck disable=SC1091
      source .r2lab_config
      SELECTED_R2LAB_USERNAME=${R2LAB_USERNAME:-}
      echo "Using saved R2Lab credentials for ${SELECTED_R2LAB_USERNAME:-unknown}"
    else
      read -r -p "R2Lab username (slice name): " SELECTED_R2LAB_USERNAME
      read -r -p "R2Lab account email: " R2LAB_EMAIL
      read -r -s -p "R2Lab password: " R2LAB_PASSWORD
      echo
      ( umask 077
        printf 'R2LAB_USERNAME=%q\nR2LAB_EMAIL=%q\nR2LAB_PASSWORD=%q\n' \
          "$SELECTED_R2LAB_USERNAME" "$R2LAB_EMAIL" "$R2LAB_PASSWORD" > .r2lab_config
      )
    fi
    [[ -n "$SELECTED_R2LAB_USERNAME" ]] || { echo "R2Lab username is required" >&2; exit 2; }
    read -r -p "Reserve the R2Lab testbed? [Y/n]: " R2LAB_RESERVE_CHOICE
    SELECTED_R2LAB_RESERVE=true
    SELECTED_R2LAB_DURATION=120
    [[ "${R2LAB_RESERVE_CHOICE:-y}" =~ ^[Nn]$ ]] && SELECTED_R2LAB_RESERVE=false
    if $SELECTED_R2LAB_RESERVE; then
      read -r -p "R2Lab reservation duration in minutes [120]: " SELECTED_R2LAB_DURATION
      SELECTED_R2LAB_DURATION=${SELECTED_R2LAB_DURATION:-120}
      [[ "$SELECTED_R2LAB_DURATION" =~ ^[1-9][0-9]*$ ]] || { echo "R2Lab duration must be a positive integer" >&2; exit 2; }
    fi
  else
    SELECTED_R2LAB_USERNAME=""
    SELECTED_R2LAB_RESERVE=false
    SELECTED_R2LAB_DURATION=120
  fi

  choose_sop_node "core" "sopnode-f2"; SELECTED_CORE_NODE="$SELECTED_NODE"
  choose_sop_node "RAN" "sopnode-f3"; SELECTED_RAN_NODE="$SELECTED_NODE"
  choose_sop_node "broker" "$SELECTED_CORE_NODE"; SELECTED_BROKER_NODE="$SELECTED_NODE"
  read -r -p "5G profile [default]: " SELECTED_PROFILE; SELECTED_PROFILE=${SELECTED_PROFILE:-default}
  read -r -p "Ensure selected SOP nodes are reserved? [Y/n]: " RESERVE_CHOICE
  if [[ "${RESERVE_CHOICE:-y}" =~ ^[Nn]$ ]]; then
    SELECTED_RESERVE=false
  else
    SELECTED_RESERVE=true
    read -r -p "Reservation duration in minutes [120]: " SELECTED_DURATION; SELECTED_DURATION=${SELECTED_DURATION:-120}
    [[ "$SELECTED_DURATION" =~ ^[1-9][0-9]*$ ]] || { echo "Duration must be a positive integer" >&2; exit 2; }
    read -r -p "POS image [ubuntu-jammy]: " SELECTED_POS_IMAGE; SELECTED_POS_IMAGE=${SELECTED_POS_IMAGE:-ubuntu-jammy}
  fi
  SELECTED_DURATION=${SELECTED_DURATION:-120}; SELECTED_POS_IMAGE=${SELECTED_POS_IMAGE:-ubuntu-jammy}
  if [[ "$SELECTED_PLATFORM" == rfsim ]]; then DEFAULT_UES="uesim01,uesim02"; else DEFAULT_UES="qhat01"; fi
  read -r -p "UEs, comma-separated [$DEFAULT_UES]: " SELECTED_UES; SELECTED_UES=${SELECTED_UES:-$DEFAULT_UES}

  CONFIG="$RUN_DIR/interactive-scenario.yml"
  "$SYNTHRAN_PYTHON" - scenarios/reference.yml "$CONFIG" "$SELECTED_CORE" "$SELECTED_RAN" "$SELECTED_PLATFORM" "$SELECTED_RU" "$SELECTED_CORE_NODE" "$SELECTED_RAN_NODE" "$SELECTED_BROKER_NODE" "$SELECTED_PROFILE" "$SELECTED_UES" "$SELECTED_R2LAB_USERNAME" "$SELECTED_RESERVE" "$SELECTED_DURATION" "$SELECTED_POS_IMAGE" "$SELECTED_R2LAB_RESERVE" "$SELECTED_R2LAB_DURATION" <<'PY'
import copy, sys, yaml
from pathlib import Path
source, output, core, ran, platform, ru, core_node, ran_node, broker_node, profile, ue_csv, r2lab_username, reserve, duration, pos_image, r2_reserve, r2_duration = sys.argv[1:]
scenario = yaml.safe_load(Path(source).read_text())
ues = [name.strip() for name in ue_csv.split(',') if name.strip()]
if not ues: raise SystemExit('At least one UE is required')
if ran == 'srsran' and platform == 'rfsim' and len(ues) > 3: raise SystemExit('srsRAN RFSIM supports at most three srsUEs')
if platform == 'r2lab' and ran == 'ueransim': raise SystemExit('UERANSIM is a software RAN and cannot drive an R2Lab physical radio')
scenario['deployment'].update({'core': core, 'ran': ran, 'platform': platform, 'profile': profile, 'ru': ru, 'nodes': {'core': core_node, 'ran': ran_node, 'broker': broker_node}, 'ues': ues})
scenario['deployment']['reservation'] = {'enabled': reserve == 'true', 'duration_minutes': int(duration), 'image': pos_image}
scenario['deployment']['r2lab_reservation'] = {'enabled': r2_reserve == 'true', 'duration_minutes': int(r2_duration)}
if r2lab_username: scenario['deployment']['r2lab_username'] = r2lab_username
defaults = list(scenario['devices'].values())
scenario['devices'] = {name: copy.deepcopy(defaults[index % len(defaults)]) for index, name in enumerate(ues)}
Path(output).write_text(yaml.safe_dump(scenario, sort_keys=False))
PY

  echo
  echo "Deployment summary"
  echo "  Core:     $SELECTED_CORE on $SELECTED_CORE_NODE"
  echo "  RAN:      $SELECTED_RAN on $SELECTED_RAN_NODE"
  echo "  Platform: $SELECTED_PLATFORM ($SELECTED_RU)"
  echo "  Broker:   $SELECTED_BROKER_NODE"
  echo "  UEs:      $SELECTED_UES"
  echo "  Profile:  $SELECTED_PROFILE"
  echo "  POS:      $SELECTED_RESERVE, ${SELECTED_DURATION}m, image $SELECTED_POS_IMAGE"
  [[ "$SELECTED_PLATFORM" == r2lab ]] && echo "  R2Lab:    $SELECTED_R2LAB_RESERVE, ${SELECTED_R2LAB_DURATION}m"
  read -r -p "Continue? [Y/n]: " CONFIRM_DEPLOY
  [[ ! "${CONFIRM_DEPLOY:-y}" =~ ^[Nn]$ ]] || exit 0
fi

if ! $NO_RESERVATION && ! $DRY_RUN; then
  deployment_section "Resolving the SOP reservation"
  command -v pos >/dev/null || { echo "POS reservation requested but the pos command is unavailable" >&2; exit 1; }
  "$SYNTHRAN_PYTHON" deployment/scripts/reserve_sop.py "$CONFIG" "$RUN_DIR"
  SOP_RESERVATION_DONE=true
fi

deployment_section "Generating the energy-aware sensor trace"
"$SYNTHRAN_PYTHON" -m synthran.cli model run --config "$CONFIG" --output "$RUN_DIR/model"
"$SYNTHRAN_PYTHON" - "$CONFIG" "$RUN_DIR" <<'PY'
import os, socket, sys, yaml
from pathlib import Path
c=yaml.safe_load(Path(sys.argv[1]).read_text()); d=c['deployment']; nodes=d['nodes']; ues=d['ues']
if d['ran'].lower() == 'srsran' and len(ues) > 3: raise SystemExit('srsRAN RFSIM supports at most three srsUE devices')
if d['platform'] == 'r2lab' and d['ran'].lower() == 'ueransim': raise SystemExit('UERANSIM cannot be combined with an R2Lab physical radio')
if d['platform'] == 'r2lab':
    r2user = d.get('r2lab_username', os.environ.get('R2LAB_USERNAME',''))
    identity = os.environ.get('R2LAB_IDENTITY_FILE', '')
    key_arg = f" ansible_ssh_private_key_file={identity}" if identity else ''
    physical_hosts = [f"{ue} ansible_user=root{key_arg} ansible_ssh_common_args='-o ProxyJump={r2user}@faraday.inria.fr'" for ue in ues]
elif d['platform'] == 'physical':
    physical_hosts = ues
else:
    physical_hosts = []
def host_entry(name):
    return f'{name} ip={socket.gethostbyname(name)}'
if d['platform'] == 'r2lab':
    identity = os.environ.get('R2LAB_IDENTITY_FILE', '')
    key_arg = f" ansible_ssh_private_key_file={identity}" if identity else ''
    faraday = [f"faraday_host ansible_host=faraday.inria.fr ansible_user={d.get('r2lab_username', os.environ.get('R2LAB_USERNAME',''))}{key_arg}"]
else:
    faraday = []
lines=['[core_node]', host_entry(nodes['core']), '', '[ran_node]', host_entry(nodes['ran']), '', '[broker_node]', host_entry(nodes.get('broker',nodes['core'])), '', '[physical_ues]']+physical_hosts+['', '[faraday]']+faraday+['', '[k8s_workers:children]','ran_node','', '[sopnodes:children]','core_node','ran_node']
Path(sys.argv[2],'inventory.ini').write_text('\n'.join(lines)+'\n')
ue_map=[{'device':name,'index':i+1,'interface':f'tun_srsue{i+1}'} for i,name in enumerate(ues)]
variables={'core':d['core'],'ran':d['ran'],'rru':'rfsim' if d['platform']=='rfsim' else d.get('ru',d['platform']),'platform':d['platform'],'fiveg_profile':d.get('profile','default'),'core_node_name':nodes['core'],'ran_node_name':nodes['ran'],'broker_node_name':nodes.get('broker',nodes['core']),'bridge_enabled':d.get('bridge_enabled',True),'fhi72':False,'f3_ran':False,'aw2s':False,'run_dir':str(Path(sys.argv[2]).resolve()),'scenario_file':str(Path(sys.argv[1]).resolve()),'mqtt_start_delay_seconds':c['mqtt'].get('start_delay_seconds',30),'mqtt_broker_address':c['mqtt'].get('broker_address'),'mqtt_port':c['mqtt'].get('port',1883),'mqtt_qos':c['mqtt'].get('qos',1),'mqtt_topic_prefix':c['mqtt'].get('topic_prefix','synthran'),'ue_count':len(ues),'synthran_ue_map':ue_map}
Path(sys.argv[2],'deployment-vars.yml').write_text(yaml.safe_dump(variables,sort_keys=False))
PY
if $DRY_RUN; then echo "Prepared $RUN_DIR; deployment skipped"; exit 0; fi

if ! $NO_RESERVATION && ! $SOP_RESERVATION_DONE; then
  deployment_section "Preparing SOP node reservations"
  mapfile -t POS_SETTINGS < <("$SYNTHRAN_PYTHON" - "$CONFIG" <<'PY'
import sys, yaml
from pathlib import Path
d = yaml.safe_load(Path(sys.argv[1]).read_text())['deployment']
r = d.get('reservation', {})
print('true' if r.get('enabled', True) else 'false')
print(int(r.get('duration_minutes', 120)))
print(r.get('image', 'ubuntu-jammy'))
for node in dict.fromkeys(d['nodes'].values()): print(node)
PY
  )
  if [[ "${POS_SETTINGS[0]}" == true ]]; then
    command -v pos >/dev/null || { echo "POS reservation requested but the pos command is unavailable" >&2; exit 1; }
    POS_DURATION=${POS_SETTINGS[1]}; POS_IMAGE=${POS_SETTINGS[2]}; POS_NODES=("${POS_SETTINGS[@]:3}")
    POS_REUSED=false; POS_RESERVED=false; POS_LAST_ERROR=""
    echo "Requesting up to ${POS_DURATION} minutes for: ${POS_NODES[*]}"
    POS_OWNER=${USER:-$(id -un)}
    pos calendar list --filter "owner=$POS_OWNER" --json > "$RUN_DIR/pos-calendar-owner.json"
    if ! POS_COVERAGE_OUTPUT=$("$SYNTHRAN_PYTHON" - \
      "$RUN_DIR/pos-calendar-owner.json" "$POS_DURATION" "${POS_NODES[@]}" <<'PY'
import json, math, sys
from datetime import datetime
events = json.load(open(sys.argv[1], encoding='utf-8'))
nodes = sys.argv[3:]; now = datetime.now()
def stamp(value): return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
active_ends = {}
for node in nodes:
    active = [stamp(e['end_date']) for e in events
              if node in e['nodes'] and stamp(e['start_date']) <= now < stamp(e['end_date'])]
    if active:
        active_ends[node] = max(active)
if active_ends and len(active_ends) != len(nodes):
    missing = sorted(set(nodes) - set(active_ends))
    raise SystemExit(f'Only part of the requested SOP set has active calendar coverage; missing {missing}')
if not active_ends:
    print('fresh')
else:
    print('reuse')
    remaining = min(math.floor((end - now).total_seconds() / 60)
                    for end in active_ends.values())
    common_end = min(active_ends.values())
    print(f'duration|{max(0, remaining)}')
    print(f'end|{common_end:%Y-%m-%dT%H:%M}')
PY
    ); then
      echo "Unable to reconcile the current SOP calendar coverage" >&2
      exit 1
    fi
    mapfile -t POS_COVERAGE <<< "$POS_COVERAGE_OUTPUT"
    if [[ "${POS_COVERAGE[0]}" == reuse ]]; then
      POS_REUSED=true; POS_RESERVED=true; POS_ACTUAL_DURATION=0; POS_CALENDAR_END=""
      for coverage in "${POS_COVERAGE[@]:1}"; do
        IFS='|' read -r action node start extension <<< "$coverage"
        if [[ "$action" == duration ]]; then
          POS_ACTUAL_DURATION=$node
        elif [[ "$action" == end ]]; then
          POS_CALENDAR_END=$node
        fi
      done
      echo "Reusing the active allocation unchanged; calendar coverage ends at $POS_CALENDAR_END (${POS_ACTUAL_DURATION} minutes remain)"
    else
      for ((candidate=POS_DURATION; candidate>=10; candidate-=10)); do
        if POS_OUTPUT=$(pos calendar create --start now --duration "$candidate" "${POS_NODES[@]}" 2>&1); then
          POS_RESERVED=true; POS_ACTUAL_DURATION=$candidate
          printf '%s\n' "$POS_OUTPUT" | tee "$RUN_DIR/pos-allocation.log"
          break
        fi
        POS_LAST_ERROR=$POS_OUTPUT
        [[ "$POS_OUTPUT" =~ [Cc]alendar|[Cc]onflict|[Uu]navailable|fit ]] || break
      done
      if $POS_RESERVED; then
        POS_OUTPUT=$(pos allocations allocate "${POS_NODES[@]}" 2>&1) || {
          printf '%s\n' "$POS_OUTPUT" >&2
          echo "Calendar reservation succeeded, but POS could not allocate the selected nodes" >&2
          exit 1
        }
        printf '%s\n' "$POS_OUTPUT" | tee -a "$RUN_DIR/pos-allocation.log"
      fi
    fi
    if ! $POS_RESERVED; then
      printf '%s\n' "$POS_LAST_ERROR" >&2
      echo "Unable to reserve these nodes for any usable duration; they may belong to another user" >&2
      exit 1
    fi
    echo "POS allocation ready for ${POS_ACTUAL_DURATION} minutes from now"
    if $POS_REUSED; then
      echo "Reusing existing node state; skipping image selection and reset"
    else
      for node in "${POS_NODES[@]}"; do
        echo "Selecting image $POS_IMAGE on $node"
        pos nodes image "$node" "$POS_IMAGE" 2>&1 | tee -a "$RUN_DIR/pos-provisioning.log"
      done
      for node in "${POS_NODES[@]}"; do
        echo "Resetting and waiting for $node to finish booting"
        pos nodes reset --blocking --verbose "$node" 2>&1 | tee -a "$RUN_DIR/pos-provisioning.log"
      done
    fi

  fi
fi

mapfile -t R2LAB_SETTINGS < <("$SYNTHRAN_PYTHON" - "$CONFIG" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))['deployment']
r = d.get('r2lab_reservation', {})
print(d.get('platform', 'rfsim'))
print('true' if r.get('enabled', True) else 'false')
print(int(r.get('duration_minutes', 120)))
PY
)
if [[ "${R2LAB_SETTINGS[0]}" == r2lab && "${R2LAB_SETTINGS[1]}" == true && "$NO_RESERVATION" == false ]]; then
  deployment_section "Preparing the R2Lab reservation"
  R2LAB_DURATION=${R2LAB_SETTINGS[2]}
  [[ -f .r2lab_config ]] || { echo "R2Lab credentials are missing from .r2lab_config" >&2; exit 1; }
  # shellcheck disable=SC1091
  source .r2lab_config
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
  # Match the original 5g_ansible flow: use the operator's normal SSH
  # configuration and run rhubarbe directly on Faraday. Select Duckburg's
  # non-standard R2Lab identity explicitly when it is present.
  R2LAB_SSH=(ssh)
  if [[ -n "${R2LAB_IDENTITY_FILE:-}" ]]; then
    R2LAB_SSH+=(-i "$R2LAB_IDENTITY_FILE" -o IdentitiesOnly=yes)
    echo "Using R2Lab SSH identity: $R2LAB_IDENTITY_FILE"
  fi
  echo "Checking SSH access to $R2LAB_USERNAME@faraday.inria.fr"
  if ! "${R2LAB_SSH[@]}" -o BatchMode=yes -o ConnectTimeout=15 \
    "$R2LAB_USERNAME@faraday.inria.fr" true; then
    echo "R2Lab SSH authentication failed; no reservation was attempted" >&2
    exit 1
  fi
  R2LAB_LEASE_CHECK=$("${R2LAB_SSH[@]}" "$R2LAB_USERNAME@faraday.inria.fr" \
    "rhubarbe leases --check" 2>&1) && R2LAB_LEASE_ACTIVE=true || R2LAB_LEASE_ACTIVE=false
  if $R2LAB_LEASE_ACTIVE; then
    printf '%s\n' "$R2LAB_LEASE_CHECK" | tee "$RUN_DIR/r2lab-reservation.log"
    echo "Reusing the active R2Lab lease owned by $R2LAB_USERNAME"
  else
    echo "No active owned R2Lab lease was found; requesting a new lease"
    if ! "${R2LAB_SSH[@]}" "$R2LAB_USERNAME@faraday.inria.fr" "$R2LAB_REMOTE_COMMAND" \
    2>&1 | tee "$RUN_DIR/r2lab-reservation.log"; then
      echo "R2Lab reservation failed; the separate SOP allocation was left intact" >&2
      exit 1
    fi
  fi
fi

deployment_section "Preparing Ansible dependencies"
if ! ansible-galaxy collection install -r deployment/collections/requirements.yml >"$RUN_DIR/ansible-galaxy.log" 2>&1; then
  cat "$RUN_DIR/ansible-galaxy.log" >&2
  echo "Ansible dependency preparation failed; full output: $RUN_DIR/ansible-galaxy.log" >&2
  exit 1
fi

deployment_section "Provisioning nodes and deploying the selected 5G stack"
export ANSIBLE_CONFIG="$PWD/deployment/ansible.cfg"
export ANSIBLE_FORCE_COLOR=0
ANSIBLE_COMMAND=(ansible-playbook -i "$RUN_DIR/inventory.ini"
  -e "@deployment/group_vars/all/all.yml"
  -e "@$RUN_DIR/deployment-vars.yml"
  deployment/playbooks/site.yml)
if $VERBOSE; then
  ANSIBLE_COMMAND+=(--verbose)
fi
echo "Showing deployment stages, retries, warnings, and failures; full host results are saved to $RUN_DIR/ansible.log"
echo
set +e
"${ANSIBLE_COMMAND[@]}" 2>&1 \
  | tee "$RUN_DIR/ansible.log" \
  | awk '
      function important(line) {
        return line ~ /^(PLAY|TASK|RUNNING HANDLER|FAILED - RETRYING|fatal:|UNREACHABLE!|NO MORE HOSTS LEFT|PLAY RECAP|\[WARNING\]|\[DEPRECATION WARNING\])/
      }
      important($0) {
        suppress_result = 0
        line = $0
        if (line ~ /^(PLAY|TASK|RUNNING HANDLER)/) {
          sub(/[[:space:]]+\*+$/, "", line)
        }
        print line
        fflush()
        next
      }
      /^(ok|changed|skipping|included): \[/ {
        if ($0 ~ /=> \{$/) {
          suppress_result = 1
        }
        next
      }
      suppress_result { next }
      /^[[:space:]]*$/ { next }
      {
        print
        fflush()
      }
    '
ANSIBLE_RC=${PIPESTATUS[0]}
set -e
if (( ANSIBLE_RC != 0 )); then
  echo "Deployment failed; complete Ansible output: $RUN_DIR/ansible.log" >&2
  exit "$ANSIBLE_RC"
fi

deployment_section "Reconciling model, publisher, and broker results"
"$SYNTHRAN_PYTHON" - "$RUN_DIR" <<'PY'
import sys
from pathlib import Path
run=Path(sys.argv[1]); rows=[]
for source in sorted(run.glob('publisher-*.jsonl')): rows.extend(source.read_text().splitlines())
(run/'publisher.jsonl').write_text('\n'.join(rows)+('\n' if rows else ''))
PY
"$SYNTHRAN_PYTHON" -m synthran.cli results reconcile --expected "$RUN_DIR/model/events.jsonl" --publisher "$RUN_DIR/publisher.jsonl" --broker "$RUN_DIR/broker.jsonl" --output "$RUN_DIR/summary.json"
echo "Artifacts retained in $RUN_DIR"
