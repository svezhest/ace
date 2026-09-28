#!/bin/bash
# запись EvoLib: eval_main.py апстрима на LiveCodeBench v6 hard (README, раздел LiveCodeBench), первые N задач без
# повторов (--n_iterations N). Модель — через прокси записи (tools/record), эмбеддинги — BGE-M3 стенда
# (tools/record/embeddings.py). sitecustomize.py: AzureOpenAI -> OpenAI на --endpoint, random.seed(0).
# Синтетических тестов апстрим не выложил — их файл строит syn_tests.py из публичных тестов задач.
# Живая модель: шлюз обязан стоять с GATEWAY_OPENAI_DEFAULTS=1 — апстрим (путь o4-mini) не передаёт temperature.
# usage: run.sh OUT   (OUT/rec.jsonl — запись, OUT/evolib.log — лог апстрима, OUT/run.log — его вывод,
# OUT/syn_tests.json — синтетические тесты; MODEL_URL — другой сервер модели, тогда шлюз не проверяется)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
U=${UPSTREAMS:-$HOME/Projects/upstreams}
ACE=${ACE:-$(cd "$HERE/../.." && pwd)}
N=${N:-15}
PORT=${PORT:-8090}
EMB_PORT=${EMB_PORT:-8092}
if [ -z "${MODEL_URL:-}" ]; then
  pid=$(pgrep -x qwen-gateway | head -1 || true)
  ps eww -o command= -p "$pid" | tr ' ' '\n' | grep -x GATEWAY_OPENAI_DEFAULTS=1 >/dev/null ||
    { echo "шлюз без GATEWAY_OPENAI_DEFAULTS=1: у запросов апстрима не будет T=1" >&2; exit 1; }
fi
(cd "$ACE" && HF_HUB_OFFLINE=1 exec .venv/bin/python -m tools.record.embeddings --port $EMB_PORT) &
EMB=$!
(cd "$ACE" && exec .venv/bin/python -m tools.record.record "$OUT/rec.jsonl" --port $PORT \
    --upstream "${MODEL_URL:-http://localhost:8080}" --embeddings-upstream http://127.0.0.1:$EMB_PORT) &
trap "kill $EMB $!" EXIT
for p in $PORT $EMB_PORT; do
  for i in $(seq 60); do (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null && break; sleep 1; done
done
cd "$U/LiveCodeBench"       # lcb_runner читает примеры промптов по путям от корня своего репозитория
export PYTHONPATH="$HERE:$U/LiveCodeBench" HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TIKTOKEN_CACHE_DIR="$U/.tiktoken" \
    PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
"$U/.venvs/evolib/bin/python" "$HERE/syn_tests.py" "$OUT/syn_tests.json"
"$U/.venvs/evolib/bin/python" "$U/EvoLib/EvoLib/eval_main.py" --task livecodebench --model ornith15-9b \
    --k_q_per_problem 3 --n_iterations "$N" --endpoint http://127.0.0.1:$PORT/v1 \
    --embedding_endpoint http://127.0.0.1:$PORT/v1 --syn_test_data_file "$OUT/syn_tests.json" \
    --log_file "$OUT/evolib.log" 2>&1 | tee "$OUT/run.log"
