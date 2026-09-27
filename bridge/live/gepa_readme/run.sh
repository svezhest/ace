#!/bin/bash
# запись GEPA: квикстарт README (run.py), модель — через прокси записи (tools/record, --seed).
# usage: run.sh OUT   (OUT/rec.jsonl — запись, OUT/steps.json — снимки состояния, OUT/gepa.log — вывод)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
U=${UPSTREAMS:-$HOME/Projects/upstreams}
ACE=${ACE:-$(cd "$HERE/../../.." && pwd)}
PORT=${PORT:-8090}
(cd "$ACE" && exec .venv/bin/python -m tools.record.record "$OUT/rec.jsonl" --port $PORT \
    --upstream "${MODEL_URL:-http://localhost:8080}" --seed) &
trap "kill $!" EXIT
for i in $(seq 60); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && break; sleep 1; done
OPENAI_BASE_URL=http://127.0.0.1:$PORT/v1 OPENAI_API_KEY=x HF_HUB_OFFLINE=1 LITELLM_LOCAL_MODEL_COST_MAP=True \
    PYTHONUNBUFFERED=1 UPSTREAMS=$U "$U/.venvs/gepa/bin/python" "$HERE/run.py" "$OUT" 2>&1 | tee "$OUT/gepa.log"
