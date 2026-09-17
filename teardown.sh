#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
export PATH="$HOME/.local/bin:$PATH"

if [[ -f .r2lab_config ]]; then
  # Release credentials remain outside the repository and are passed to the
  # authenticated provider helper through stdin, never through process argv.
  set -a
  # shellcheck disable=SC1091
  source .r2lab_config
  set +a
fi

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
SYNTHRAN_PYTHON="$(python3 -m synthran.runtime python)"
"$SYNTHRAN_PYTHON" -m synthran.runtime deployment --log /tmp/synthran-teardown-bootstrap.log

exec "$SYNTHRAN_PYTHON" -m synthran.teardown_controller "$@"
