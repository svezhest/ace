#!/bin/bash
# запись GEPA: квикстарт README (README.md:72-92) дословно, кроме имени модели; модель — через прокси записи
# (tools/record). usage: run.sh OUT   (OUT/rec.jsonl — запись, OUT/gepa.log — вывод квикстарта)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
ACE=${ACE:-$(cd "$HERE/../.." && pwd)}
U=${UPSTREAMS:-$ACE/upstreams}
PORT=${PORT:-8090}
(cd "$ACE" && exec .venv/bin/python -m tools.record.record "$OUT/rec.jsonl" --port $PORT \
    --upstream "${MODEL_URL:-http://localhost:8080}") &
trap "kill $!" EXIT
for i in $(seq 60); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && break; sleep 1; done
cd "$OUT"
OPENAI_BASE_URL=http://127.0.0.1:$PORT/v1 OPENAI_API_KEY=x HF_HOME=$U/.hf HF_HUB_OFFLINE=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True PYTHONHASHSEED=0 PYTHONUNBUFFERED=1 PYTHONPATH="$U/gepa/src" \
    "$U/.venvs/gepa/bin/python" "$HERE/quickstart.py" 2>&1 | tee "$OUT/gepa.log"
