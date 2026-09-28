#!/bin/bash
# запись MCE: scripts/train_symptom_diagnosis.sh апстрима (python -m mce.main) с урезанием его же аргументами,
# затем тест лучшей по val итерации штатным python -m mce.eval отдельным процессом. Копия апстрима (git archive) в
# фиксированном ROOT (пути входят в промпты агентов), окружение с нуля (env -i, env.txt). Модель — через прокси записи
# (tools/record); агенты Claude CLI говорят Anthropic Messages, их переводит LiteLLM (litellm.yaml).
# usage: run.sh OUT   (OUT/rec.jsonl — запись, OUT/train.log и OUT/test.log — вывод, OUT/workspace, OUT/logs,
# OUT/test — выход апстрима)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
U=${UPSTREAMS:-$HOME/Projects/upstreams}
ACE=${ACE:-$(cd "$HERE/../.." && pwd)}
PORT=${PORT:-8090}
LPORT=${LITELLM_PORT:-4000}
ROOT=/private/tmp/mce-symptom
rm -rf "$ROOT"
mkdir -p "$ROOT/home" "$ROOT/tmp"
git -C "$U/meta-context-engineering" archive c4b7a7c | tar -x -C "$ROOT"
ln -s "$U/.venvs/mce" "$ROOT/.venv"
sed "s#@PORT@#$PORT#" "$HERE/litellm.yaml" > "$OUT/litellm.yaml"
(cd "$ACE" && exec .venv/bin/python -m tools.record.record "$OUT/rec.jsonl" --port $PORT \
    --upstream "${MODEL_URL:-http://localhost:8080}") &
REC=$!
LITELLM_LOCAL_MODEL_COST_MAP=True "$U/.venvs/litellm/bin/litellm" --config "$OUT/litellm.yaml" --host 127.0.0.1 \
    --port $LPORT > "$OUT/litellm.log" 2>&1 &
trap "kill $REC $!" EXIT
for p in $PORT $LPORT; do
    for i in $(seq 120); do (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null && break; sleep 1; done
done
E=$(sed "s#@ROOT@#$ROOT#g; s#@UV@#$(dirname "$(command -v uv)")#g; s#@PORT@#$PORT#g; s#@LPORT@#$LPORT#g" "$HERE/env.txt")
cd "$ROOT"
# у апстрима выборка train — random без сида
env -i $E .venv/bin/python -c "import random, runpy, sys; random.seed(0); sys.argv = ['mce.main'] + sys.argv[1:]
runpy.run_module('mce.main', run_name='__main__')" \
    --workspace workspace/symptom_diagnosis --env symptom_diagnosis \
    --train-data env/symptom_diagnosis/data/train.jsonl --val-data env/symptom_diagnosis/data/val.jsonl \
    --model ornith15-9b --iterations 2 --train-limit 4 --val-limit 2 --train-batch-size 2 \
    --log-dir logs/symptom_diagnosis 2>&1 | tee "$OUT/train.log"
# лучшая по val итерация — как max в mce.main: при равенстве первая
BEST=$(.venv/bin/python -c "import json; e = json.load(open('workspace/symptom_diagnosis/meta_agent/evaluations.json'))
print(e[max(e, key=lambda k: e[k]['val_accuracy'])]['last_sub_folder'])")
env -i $E .venv/bin/python -m mce.eval --iter_dir "workspace/symptom_diagnosis/$BEST" --env symptom_diagnosis \
    --data env/symptom_diagnosis/data/test.jsonl --limit 2 --model ornith15-9b --save-results-to test \
    2>&1 | tee "$OUT/test.log"
cp -R workspace logs test "$OUT/"
