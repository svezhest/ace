#!/bin/bash
# запись SCOPE: examples/test_scope_deep.py апстрима как есть, модель — через прокси записи (tools/record, --seed).
# usage: run.sh OUT   (OUT/rec.jsonl — запись, OUT/stdout.txt — вывод сценария; память сценарий держит во
# временном каталоге и в конце сам удаляет, так что снимок состояния — только его вывод)
set -eu
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
U=${UPSTREAMS:-$HOME/Projects/upstreams}
ACE=${ACE:-$(cd "$(dirname "$0")/../../.." && pwd)}
PORT=${PORT:-8094}
(cd "$ACE" && exec .venv/bin/python -m tools.record.record "$OUT/rec.jsonl" --port $PORT \
    --upstream "${MODEL_URL:-http://localhost:8080}" --seed) &
trap "kill $!" EXIT
for i in $(seq 60); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && break; sleep 1; done
cd "$U/SCOPE"
# код выхода сценария — доля пройденных проверок (1 при < 70%), поэтому готовность — по итоговой сводке
"$U/.venvs/light/bin/python" examples/test_scope_deep.py --provider openai --model ornith15-9b --api-key x \
    --base-url http://127.0.0.1:$PORT/v1 2>&1 | tee "$OUT/stdout.txt" || true
grep -q "TEST SUMMARY" "$OUT/stdout.txt"
