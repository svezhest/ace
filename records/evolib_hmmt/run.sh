#!/bin/bash
# запись EvoLib: eval_main.py апстрима на HMMT (README, раздел HMMT), первые N задач без повторов (--n_iterations N,
# все из hmmt_feb_2025), k по умолчанию кода. Окружение — как у ../evolib/run.sh: апстрим целиком в контейнере
# evolib-upstream (образ — ../evolib/Dockerfile), сеть — внутренняя evonet, единственный выход — контейнер записи evorec
# (tools/record) к шлюзу и эмбеддингам на хосте. sitecustomize.py: AzureOpenAI -> OpenAI на --endpoint,
# random.seed(0) и переходник вызова extract_and_grade к сигнатуре matharena e927660. Шлюз обязан стоять с
# GATEWAY_OPENAI_DEFAULTS=1: апстрим (путь o4-mini) не передаёт temperature.
# usage: run.sh OUT   (OUT/rec.jsonl — запись, OUT/evolib.log и OUT/evolib.*.json — лог и чекпойнт апстрима,
# OUT/run.log — его вывод; MODEL_URL — другой сервер модели, тогда шлюз не проверяется)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
U=${UPSTREAMS:-$HOME/Projects/upstreams}
ACE=${ACE:-$(cd "$HERE/../.." && pwd)}
N=${N:-12}
EMB_PORT=${EMB_PORT:-8092}
if [ -z "${MODEL_URL:-}" ]; then
  pid=$(pgrep -x qwen-gateway | head -1 || true)
  ps eww -o command= -p "$pid" | tr ' ' '\n' | grep -x GATEWAY_OPENAI_DEFAULTS=1 >/dev/null ||
    { echo "шлюз без GATEWAY_OPENAI_DEFAULTS=1: у запросов апстрима не будет T=1" >&2; exit 1; }
fi
mkdir -p "$OUT/rec" "$OUT/out"
(cd "$ACE" && HF_HUB_OFFLINE=1 exec .venv/bin/python -m tools.record.embeddings --port $EMB_PORT) &
EMB=$!
trap 'kill $EMB; docker rm -f evorec >/dev/null' EXIT
for i in $(seq 120); do (exec 3<>/dev/tcp/127.0.0.1/$EMB_PORT) 2>/dev/null && break; sleep 1; done
docker network inspect evonet >/dev/null 2>&1 || docker network create --internal evonet >/dev/null
docker run -d --rm --name evorec --network bridge -v "$ACE/tools":/ace/tools:ro -v "$OUT/rec":/out -e PYTHONPATH=/ace \
    -e PYTHONDONTWRITEBYTECODE=1 evolib-upstream python -c "
from pathlib import Path
from tools.record.record import Recorder
Recorder(('0.0.0.0', 8080), Path('/out/rec.jsonl'), '${MODEL_URL:-http://host.docker.internal:8080}',
         'http://host.docker.internal:$EMB_PORT').serve_forever()" >/dev/null
docker network connect evonet evorec
docker run --rm --name evorun --network evonet --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 \
    --memory 4g -v "$U/EvoLib":/up/EvoLib:ro -v "$U/matharena":/up/matharena:ro -v "$U/.hf-evolib":/hf:ro \
    -v "$U/.tiktoken":/tiktoken:ro -v "$HERE/sitecustomize.py":/site/sitecustomize.py:ro -v "$OUT/out":/out \
    -e PYTHONPATH=/site:/up/matharena/src -e HF_HOME=/tmp/hf -e HF_HUB_OFFLINE=1 -e HF_DATASETS_OFFLINE=1 \
    -e TIKTOKEN_CACHE_DIR=/tiktoken -e PYTHONHASHSEED=0 -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONUNBUFFERED=1 \
    -e HOME=/tmp evolib-upstream sh -c "
mkdir /tmp/hf && cp -r /hf/datasets /hf/modules /tmp/hf/ && cd /up/EvoLib/EvoLib &&
python eval_main.py --task hmmt --model ornith15-9b --n_iterations $N --endpoint http://evorec:8080/v1 \
    --embedding_endpoint http://evorec:8080/v1 --log_file /out/evolib.log" 2>&1 | tee "$OUT/run.log"
mv "$OUT/rec/rec.jsonl" "$OUT/rec.jsonl"
mv "$OUT"/out/* "$OUT/"
rmdir "$OUT/rec" "$OUT/out"
