#!/bin/bash
# запись SCOPE с оптимизатором памяти: records/scope_optimizer/scenario.py (тест 1 examples/test_scope_deep.py на
# наборе JSON_checker) из корня апстрима, модель — через прокси записи (tools/record).
# usage: run.sh OUT   (OUT/rec.jsonl — запись, OUT/stdout.txt — вывод сценария с журналом SCOPE и памятью в конце)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
U=${UPSTREAMS:-$HOME/Projects/upstreams}
ACE=${ACE:-$(cd "$(dirname "$0")/../.." && pwd)}
PORT=${PORT:-8097}
(cd "$ACE" && exec .venv/bin/python -m tools.record.record "$OUT/rec.jsonl" --port $PORT \
    --upstream "${MODEL_URL:-http://localhost:8080}") &
trap "kill $!" EXIT
for i in $(seq 60); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && break; sleep 1; done
cd "$U/SCOPE"
PYTHONPATH=. "$U/.venvs/light/bin/python" "$ACE/records/scope_optimizer/scenario.py" --provider openai \
    --model ornith15-9b --api-key x --base-url http://127.0.0.1:$PORT/v1 2>&1 | tee "$OUT/stdout.txt"
