#!/bin/bash
# запись MCE: scripts/train_symptom_diagnosis.sh апстрима (python -m mce.main) с урезанием его же аргументами,
# затем тест лучшей по val итерации штатным python -m mce.eval отдельным процессом. Всё в docker: образ — Dockerfile
# (собирается, если его нет), сеть — внутренняя mcenet без выхода наружу; mcerun — апстрим (агенты исполняют Bash и
# пишут файлы только там), mcellm — LiteLLM (агенты Claude CLI говорят Anthropic Messages), mcerec — прокси записи
# (tools/record) к шлюзу на хосте, единственный выход. Окружение процессов апстрима — только env.txt (env -i).
# usage: run.sh OUT   (OUT/rec.jsonl — запись, OUT/train.log и OUT/test.log — вывод, OUT/workspace, OUT/logs,
# OUT/test — выход апстрима). Строка записи с "dropped" (клиент не дождался ответа) — запись негодна, код 1.
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
ACE=${ACE:-$(cd "$HERE/../.." && pwd)}
U=${UPSTREAMS:-$ACE/upstreams}
IMG=mce-upstream:c4b7a7c-$(cat "$HERE/Dockerfile" "$HERE/litellm.req.txt" | shasum | cut -c1-12)
ROOT=/private/tmp/mce-symptom
if ! docker image inspect $IMG >/dev/null 2>&1; then
    CTX=$(mktemp -d)
    git -C "$U/meta-context-engineering" archive --prefix=up/ c4b7a7c | tar -x -C "$CTX"
    cp "$HERE/Dockerfile" "$HERE/litellm.req.txt" "$CTX/"
    docker build -q -t $IMG "$CTX" >/dev/null
    rm -rf "$CTX"
fi
mkdir -p "$OUT/rec"
docker network inspect mcenet >/dev/null 2>&1 || docker network create --internal mcenet >/dev/null
trap 'docker rm -f mcerec mcellm mcerun >/dev/null 2>&1' EXIT
docker run -d --rm --name mcerec --network bridge -v "$ACE/tools":/ace/tools:ro -v "$OUT/rec":/out -e PYTHONPATH=/ace \
    -e PYTHONDONTWRITEBYTECODE=1 $IMG python -c "
from pathlib import Path
from tools.record.record import Recorder
Recorder(('0.0.0.0', 8080), Path('/out/rec.jsonl'), '${MODEL_URL:-http://host.docker.internal:8080}').serve_forever()" >/dev/null
docker network connect mcenet mcerec
docker run -d --rm --name mcellm --network mcenet -v "$HERE/litellm.yaml":/opt/litellm.yaml:ro \
    -e LITELLM_LOCAL_MODEL_COST_MAP=True $IMG /opt/litellm/bin/litellm --config /opt/litellm.yaml --port 4000 >/dev/null
docker run -d --rm --init --name mcerun --hostname mcerun --network mcenet --cap-drop ALL \
    --security-opt no-new-privileges --pids-limit 1024 --memory 8g $IMG sleep infinity >/dev/null
docker exec mcerun python -c "
import socket, time
for _ in range(120):
    try:
        socket.create_connection(('mcellm', 4000)).close(); socket.create_connection(('mcerec', 8080)).close(); break
    except OSError:
        time.sleep(1)"
E=()
while IFS= read -r v; do E+=("$v"); done < <(sed "s#@ROOT@#$ROOT#g" "$HERE/env.txt")
# у апстрима выборка train — random без сида
docker exec mcerun env -i "${E[@]}" .venv/bin/python -c "import random, runpy, sys; random.seed(0)
sys.argv = ['mce.main'] + sys.argv[1:]; runpy.run_module('mce.main', run_name='__main__')" \
    --workspace workspace/symptom_diagnosis --env symptom_diagnosis \
    --train-data env/symptom_diagnosis/data/train.jsonl --val-data env/symptom_diagnosis/data/val.jsonl \
    --model ornith15-9b --iterations 2 --train-limit 4 --val-limit 2 --train-batch-size 2 \
    --log-dir logs/symptom_diagnosis 2>&1 | tee "$OUT/train.log"
# лучшая по val итерация — как max в mce.main: при равенстве первая
BEST=$(docker exec mcerun .venv/bin/python -c "import json
e = json.load(open('workspace/symptom_diagnosis/meta_agent/evaluations.json'))
print(e[max(e, key=lambda k: e[k]['val_accuracy'])]['last_sub_folder'])")
docker exec mcerun env -i "${E[@]}" .venv/bin/python -m mce.eval --iter_dir "workspace/symptom_diagnosis/$BEST" \
    --env symptom_diagnosis --data env/symptom_diagnosis/data/test.jsonl --limit 2 --model ornith15-9b \
    --save-results-to test 2>&1 | tee "$OUT/test.log"
for d in workspace logs test; do docker cp -q mcerun:$ROOT/$d "$OUT/"; done
mv "$OUT/rec/rec.jsonl" "$OUT/rec.jsonl"
rmdir "$OUT/rec"
if grep -q '"dropped": true' "$OUT/rec.jsonl"; then
    echo "запись негодна: клиент не дождался ответа (dropped)" >&2
    exit 1
fi
