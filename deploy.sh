#!/usr/bin/env bash
set -euo pipefail

CONFIG="scenarios/reference.yml"; CONFIG_EXPLICIT=false; NO_INPUT=false; NO_RESERVATION=false; DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; CONFIG_EXPLICIT=true; shift 2 ;;
    -n|--no-input) NO_INPUT=true; shift ;;
    -r|--no-reservation) NO_RESERVATION=true; shift ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) echo "Usage: ./deploy.sh [--config scenarios/<scenario>.yml] [--no-input] [--no-reservation] [--dry-run]"; echo "Without options, deployment choices are prompted interactively."; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ -f "$CONFIG" ]] || { echo "Scenario not found: $CONFIG" >&2; exit 2; }
if [[ -x .venv/bin/python ]]; then
  SYNTHRAN_PYTHON=.venv/bin/python
else
  command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
  python3 -m venv .venv
  SYNTHRAN_PYTHON=.venv/bin/python
fi
"$SYNTHRAN_PYTHON" -m pip install --disable-pip-version-check -e .
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"; RUN_DIR="results/$RUN_ID"; mkdir -p "$RUN_DIR"

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
    read -r -p "R2Lab username: " SELECTED_R2LAB_USERNAME
    [[ -n "$SELECTED_R2LAB_USERNAME" ]] || { echo "R2Lab username is required" >&2; exit 2; }
  else
    SELECTED_R2LAB_USERNAME=""
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
  "$SYNTHRAN_PYTHON" - scenarios/reference.yml "$CONFIG" "$SELECTED_CORE" "$SELECTED_RAN" "$SELECTED_PLATFORM" "$SELECTED_RU" "$SELECTED_CORE_NODE" "$SELECTED_RAN_NODE" "$SELECTED_BROKER_NODE" "$SELECTED_PROFILE" "$SELECTED_UES" "$SELECTED_R2LAB_USERNAME" "$SELECTED_RESERVE" "$SELECTED_DURATION" "$SELECTED_POS_IMAGE" <<'PY'
import copy, sys, yaml
from pathlib import Path
source, output, core, ran, platform, ru, core_node, ran_node, broker_node, profile, ue_csv, r2lab_username, reserve, duration, pos_image = sys.argv[1:]
scenario = yaml.safe_load(Path(source).read_text())
ues = [name.strip() for name in ue_csv.split(',') if name.strip()]
if not ues: raise SystemExit('At least one UE is required')
if ran == 'srsran' and platform == 'rfsim' and len(ues) > 3: raise SystemExit('srsRAN RFSIM supports at most three srsUEs')
scenario['deployment'].update({'core': core, 'ran': ran, 'platform': platform, 'profile': profile, 'ru': ru, 'nodes': {'core': core_node, 'ran': ran_node, 'broker': broker_node}, 'ues': ues})
scenario['deployment']['reservation'] = {'enabled': reserve == 'true', 'duration_minutes': int(duration), 'image': pos_image}
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
  read -r -p "Continue? [Y/n]: " CONFIRM_DEPLOY
  [[ ! "${CONFIRM_DEPLOY:-y}" =~ ^[Nn]$ ]] || exit 0
fi

"$SYNTHRAN_PYTHON" -m synthran.cli model run --config "$CONFIG" --output "$RUN_DIR/model"
"$SYNTHRAN_PYTHON" - "$CONFIG" "$RUN_DIR" <<'PY'
import os, socket, sys, yaml
from pathlib import Path
c=yaml.safe_load(Path(sys.argv[1]).read_text()); d=c['deployment']; nodes=d['nodes']; ues=d['ues']
if d['ran'].lower() == 'srsran' and len(ues) > 3: raise SystemExit('srsRAN RFSIM supports at most three srsUE devices')
if d['platform'] == 'r2lab':
    r2user = d.get('r2lab_username', os.environ.get('R2LAB_USERNAME',''))
    physical_hosts = [f"{ue} ansible_user=root ansible_ssh_common_args='-o ProxyJump={r2user}@faraday.inria.fr'" for ue in ues]
elif d['platform'] == 'physical':
    physical_hosts = ues
else:
    physical_hosts = []
storage_by_node = {
    'sopnode-f1': 'sda2',
    'sopnode-f2': 'sda2',
    'sopnode-f3': 'sda2',
    'sopnode-w3': 'sdb2',
}
def host_entry(name):
    try: storage = storage_by_node[name]
    except KeyError: raise SystemExit(f'No validated containerd storage mapping for {name}')
    return f'{name} ip={socket.gethostbyname(name)} storage={storage}'
faraday = [f"faraday ansible_host=faraday.inria.fr ansible_user={d.get('r2lab_username', os.environ.get('R2LAB_USERNAME',''))}"] if d['platform']=='r2lab' else []
lines=['[core_node]', host_entry(nodes['core']), '', '[ran_node]', host_entry(nodes['ran']), '', '[broker_node]', host_entry(nodes.get('broker',nodes['core'])), '', '[physical_ues]']+physical_hosts+['', '[faraday]']+faraday+['', '[k8s_workers:children]','ran_node','', '[sopnodes:children]','core_node','ran_node','broker_node']
Path(sys.argv[2],'inventory.ini').write_text('\n'.join(lines)+'\n')
ue_map=[{'device':name,'index':i+1,'interface':f'tun_srsue{i+1}'} for i,name in enumerate(ues)]
variables={'core':d['core'],'ran':d['ran'],'rru':'rfsim' if d['platform']=='rfsim' else d.get('ru',d['platform']),'platform':d['platform'],'fiveg_profile':d.get('profile','default'),'core_node_name':nodes['core'],'ran_node_name':nodes['ran'],'broker_node_name':nodes.get('broker',nodes['core']),'bridge_enabled':d.get('bridge_enabled',True),'fhi72':False,'f3_ran':False,'aw2s':False,'run_dir':str(Path(sys.argv[2]).resolve()),'scenario_file':str(Path(sys.argv[1]).resolve()),'mqtt_start_delay_seconds':c['mqtt'].get('start_delay_seconds',30),'mqtt_broker_address':c['mqtt'].get('broker_address'),'mqtt_port':c['mqtt'].get('port',1883),'mqtt_qos':c['mqtt'].get('qos',1),'mqtt_topic_prefix':c['mqtt'].get('topic_prefix','synthran'),'ue_count':len(ues),'synthran_ue_map':ue_map}
Path(sys.argv[2],'deployment-vars.yml').write_text(yaml.safe_dump(variables,sort_keys=False))
PY
if $DRY_RUN; then echo "Prepared $RUN_DIR; deployment skipped"; exit 0; fi

if ! $NO_RESERVATION; then
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
    for ((candidate=POS_DURATION; candidate>=10; candidate-=10)); do
      if POS_OUTPUT=$(pos allocations allocate --duration "$candidate" "${POS_NODES[@]}" 2>&1); then
        POS_RESERVED=true; POS_ACTUAL_DURATION=$candidate
        printf '%s\n' "$POS_OUTPUT" | tee "$RUN_DIR/pos-allocation.log"
        break
      fi
      POS_LAST_ERROR=$POS_OUTPUT
      if [[ "$POS_OUTPUT" == *"already allocated"* ]]; then
        POS_RESERVED=true; POS_REUSED=true; POS_ACTUAL_DURATION="existing reservation"
        printf '%s\n' "$POS_OUTPUT" > "$RUN_DIR/pos-allocation.log"
        echo "Nodes are already allocated; reusing the active reservation"
        break
      fi
      [[ "$POS_OUTPUT" =~ [Cc]alendar|[Cc]onflict|[Uu]navailable|fit ]] || break
    done
    if ! $POS_RESERVED; then
      printf '%s\n' "$POS_LAST_ERROR" >&2
      echo "Unable to allocate or extend these nodes; they may belong to another user" >&2
      exit 1
    fi
    if $POS_REUSED; then
      echo "POS allocation ready using the existing reservation"
    else
      echo "POS allocation ready for ${POS_ACTUAL_DURATION} minutes from now"
    fi
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

export ANSIBLE_CONFIG="$PWD/deployment/ansible.cfg"
ansible-galaxy collection install -r deployment/collections/requirements.yml
ansible-playbook -i "$RUN_DIR/inventory.ini" \
  -e "@deployment/group_vars/all/all.yml" \
  -e "@$RUN_DIR/deployment-vars.yml" \
  deployment/playbooks/site.yml
"$SYNTHRAN_PYTHON" - "$RUN_DIR" <<'PY'
import sys
from pathlib import Path
run=Path(sys.argv[1]); rows=[]
for source in sorted(run.glob('publisher-*.jsonl')): rows.extend(source.read_text().splitlines())
(run/'publisher.jsonl').write_text('\n'.join(rows)+('\n' if rows else ''))
PY
"$SYNTHRAN_PYTHON" -m synthran.cli results reconcile --expected "$RUN_DIR/model/events.jsonl" --publisher "$RUN_DIR/publisher.jsonl" --broker "$RUN_DIR/broker.jsonl" --output "$RUN_DIR/summary.json"
echo "Artifacts retained in $RUN_DIR"
