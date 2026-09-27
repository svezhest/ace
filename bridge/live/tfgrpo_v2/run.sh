#!/bin/bash
# запись TF-GRPO: апстрим youtu-agent целиком в контейнере youtu-upstream (образ — ../tfgrpo/Dockerfile; код модели
# исполняет его python_executor только там), сеть — внутренняя tfnet без выхода наружу; единственный выход — контейнер
# записи tfrec (tools/record, --seed) к шлюзу на хосте. Обучение — 2 батча по 4 задачи DAPO-Math-17k-live, итоговый
# тест — AIME24-live (prep.py). usage: run.sh OUT DB   (DB — sqlite апстрима от prep.py; OUT/rec.jsonl — запись,
# OUT/test.db — БД прогона, OUT/tf_live_agent.yaml — итоговый агент, из БД — OUT/experiences.json, OUT/samples.json)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
mkdir -p "$OUT/rec"
cp "$2" "$OUT/test.db"
HERE=$(cd "$(dirname "$0")" && pwd)
U=${UPSTREAMS:-$HOME/Projects/upstreams}
ACE=${ACE:-$(cd "$HERE/../../.." && pwd)}
M=ornith15-9b
docker network inspect tfnet >/dev/null 2>&1 || docker network create --internal tfnet >/dev/null
docker run -d --rm --name tfrec --network bridge -v "$ACE/tools":/ace/tools:ro -v "$OUT/rec":/out -e PYTHONPATH=/ace \
    -e PYTHONDONTWRITEBYTECODE=1 youtu-upstream python -c "
from pathlib import Path
from tools.record.record import Recorder
Recorder(('0.0.0.0', 8080), Path('/out/rec.jsonl'), '${MODEL_URL:-http://host.docker.internal:8080}', None, True).serve_forever()" >/dev/null
docker network connect tfnet tfrec
trap 'docker rm -f tfrec >/dev/null' EXIT
docker run --rm --name tfrun --network tfnet --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 \
    --memory 8g -v "$U/youtu-agent":/up:ro -v "$HERE/configs":/cfg:ro -v "$HERE/sitecustomize.py":/site/sitecustomize.py:ro \
    -v "$U/.tiktoken":/tiktoken:ro -v "$OUT":/out \
    -e UTU_LLM_TYPE=chat.completions -e UTU_LLM_MODEL=$M -e UTU_LLM_BASE_URL=http://tfrec:8080/v1 -e UTU_LLM_API_KEY=x \
    -e JUDGE_LLM_TYPE=chat.completions -e JUDGE_LLM_MODEL=$M -e JUDGE_LLM_BASE_URL=http://tfrec:8080/v1 \
    -e JUDGE_LLM_API_KEY=x -e UTU_DB_URL=sqlite:////out/test.db -e TIKTOKEN_CACHE_DIR=/tiktoken -e HF_HUB_OFFLINE=1 \
    -e PYTHONPATH=/site:/tmp/up -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp youtu-upstream sh -c '
cp -r /up /tmp/up && cp -r /cfg/. /tmp/up/configs/ && cd /tmp/up &&
python scripts/run_training_free_GRPO.py --config_name math_live --experiment_name tf_live \
    --batch_size 4 --grpo_n 3 --rollout_concurrency 1 --rollout_data_truncate 8 \
    --practice_dataset_name DAPO-Math-17k-live &&
cp configs/agents/practice/tf_live_agent.yaml /out/ &&
python scripts/run_eval.py --config_name math/math_live_test --concurrency 1' 2>&1 | tee "$OUT/run.log"
python3 "$HERE/export.py" "$OUT/test.db" "$OUT"
mv "$OUT/rec/rec.jsonl" "$OUT/rec.jsonl" && rmdir "$OUT/rec"
