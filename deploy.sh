#!/usr/bin/env bash
set -euo pipefail

CONFIG=""; DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) echo "Usage: ./deploy.sh --config scenarios/<scenario>.yml [--dry-run]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$CONFIG" && -f "$CONFIG" ]] || { echo "A readable --config is required" >&2; exit 2; }
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"; RUN_DIR="results/$RUN_ID"; mkdir -p "$RUN_DIR"
python -m synthran.cli model run --config "$CONFIG" --output "$RUN_DIR/model"
python - "$CONFIG" "$RUN_DIR" <<'PY'
import sys, yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
c=yaml.safe_load(Path(sys.argv[1]).read_text()); d=c['deployment']; nodes=d['nodes']; ues=d['ues']
ue_hosts = ues if d['platform'] in {'r2lab','physical'} else [f'{ue} ansible_host={nodes["ran"]}' for ue in ues]
lines=['[core_node]', nodes['core'], '', '[ran_node]', nodes['ran'], '', '[broker_node]', nodes.get('broker',nodes['core']), '', '[ues]']+ue_hosts+['', '[sopnodes:children]','core_node','ran_node','broker_node']
Path(sys.argv[2],'inventory.ini').write_text('\n'.join(lines)+'\n')
start=(datetime.now(timezone.utc)+timedelta(seconds=c['mqtt'].get('start_delay_seconds',30))).isoformat().replace('+00:00','Z')
Path(sys.argv[2],'deployment-vars.yml').write_text(yaml.safe_dump({'core':d['core'],'ran':d['ran'],'platform':d['platform'],'fiveg_profile':d.get('profile','default'),'run_dir':str(Path(sys.argv[2]).resolve()),'scenario_file':str(Path(sys.argv[1]).resolve()),'mqtt_start_utc':start}))
PY
if $DRY_RUN; then echo "Prepared $RUN_DIR; deployment skipped"; exit 0; fi
ansible-galaxy collection install -r deployment/collections/requirements.yml
ansible-playbook -i "$RUN_DIR/inventory.ini" -e "@$RUN_DIR/deployment-vars.yml" deployment/playbooks/site.yml
python - "$RUN_DIR" <<'PY'
import sys
from pathlib import Path
run=Path(sys.argv[1]); rows=[]
for source in sorted(run.glob('publisher-*.jsonl')): rows.extend(source.read_text().splitlines())
(run/'publisher.jsonl').write_text('\n'.join(rows)+('\n' if rows else ''))
PY
python -m synthran.cli results reconcile --expected "$RUN_DIR/model/events.jsonl" --publisher "$RUN_DIR/publisher.jsonl" --broker "$RUN_DIR/broker.jsonl" --output "$RUN_DIR/summary.json"
echo "Artifacts retained in $RUN_DIR"
