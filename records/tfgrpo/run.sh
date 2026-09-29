#!/bin/bash
# запись TF-GRPO: апстрим youtu-agent (main, utu/practice) целиком в контейнере youtu-upstream (образ — Dockerfile
# рядом; код модели исполняет его python_executor только там), сеть — внутренняя tfnet без выхода наружу; единственный
# выход — контейнер записи tfrec (tools/record) к шлюзу на хосте. Обучение — 4 батча по 4 вопроса DAPO-Math-17k-live,
# итоговый тест — AIME24-live (prep.py).
# Обучение и тест — отдельные команды, как Step 5 и Step 6 README (utu/practice/README.md). Процесс апстрима может не
# выйти сам после результата: поток python_executor с кодом модели не умирает по таймауту (issue #256) и, пока жив,
# держит перехваченным stdout процесса. Поэтому шаг ждёт своей отметки в файлах (обучение — итоговый агент
# configs/agents/practice/tf_live_agent.yaml, его пишут последним; тест — «> Cleaning up...» в logs/utu.log после
# подсчёта) и гасит процесс, если тот ещё жив.
# Рандом: PYTHONHASHSEED=0, sitecustomize.py (random.seed и uuid4 от сида); стенные часы стоят (libfaketime,
# монотонные идут) — метка времени в workdir python_executor, который видит модель, одна и та же.
# Данные готовит prep.py на хосте без сети: parquet DAPO-Math-17k лежит в $UPSTREAMS/.data, AIME24 — в кэше HF
# $UPSTREAMS/.hf (records/setup_envs.sh youtu).
# usage: run.sh OUT   (в OUT: rec.jsonl — запись, test.db — БД прогона, tf_live_agent.yaml — итоговый агент,
# train.log и test.log — вывод команд, utu_train/ и utu_test/ — их logs/)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
ACE=${ACE:-$(cd "$HERE/../.." && pwd)}
U=${UPSTREAMS:-$ACE/upstreams}
mkdir -p "$OUT/rec" "$OUT/prep/data"
ln -s "$U/.data/DAPO-Math-17k" "$OUT/prep/data/"
UTU_LLM_TYPE=chat.completions UTU_LLM_MODEL=x UTU_LLM_BASE_URL=http://127.0.0.1:9/v1 UTU_LLM_API_KEY=x \
    UTU_DB_URL=sqlite:///$OUT/test.db HF_HOME=$U/.hf HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 UPSTREAMS=$U \
    "$U/.venvs/youtu/bin/python" "$HERE/prep.py" "$OUT/prep" > "$OUT/prep.log" 2>&1
rm -rf "$OUT/prep"
M=ornith15-9b
docker build -q -t youtu-upstream "$HERE" >/dev/null
docker network inspect tfnet >/dev/null 2>&1 || docker network create --internal tfnet >/dev/null
docker run -d --rm --name tfrec --network bridge -v "$ACE/tools":/ace/tools:ro -v "$OUT/rec":/out -e PYTHONPATH=/ace \
    -e PYTHONDONTWRITEBYTECODE=1 youtu-upstream python -c "
from pathlib import Path
from tools.record.record import Recorder
Recorder(('0.0.0.0', 8080), Path('/out/rec.jsonl'), '${MODEL_URL:-http://host.docker.internal:8080}').serve_forever()" >/dev/null
docker network connect tfnet tfrec
trap 'docker rm -f tfrec >/dev/null' EXIT
docker run --rm --name tfrun --network tfnet --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 \
    --memory 8g -v "$U/youtu-agent":/up:ro -v "$HERE/configs":/cfg:ro -v "$U/.tiktoken":/tiktoken:ro -v "$OUT":/out \
    -v "$HERE/sitecustomize.py":/site/sitecustomize.py:ro -e PYTHONHASHSEED=0 -e FAKETIME="2026-01-01 00:00:00" \
    -e FAKETIME_DONT_FAKE_MONOTONIC=1 -e LD_PRELOAD=/usr/local/lib/libfaketimeMT.so.1 \
    -e UTU_LLM_TYPE=chat.completions -e UTU_LLM_MODEL=$M -e UTU_LLM_BASE_URL=http://tfrec:8080/v1 -e UTU_LLM_API_KEY=x \
    -e JUDGE_LLM_TYPE=chat.completions -e JUDGE_LLM_MODEL=$M -e JUDGE_LLM_BASE_URL=http://tfrec:8080/v1 \
    -e JUDGE_LLM_API_KEY=x -e UTU_DB_URL=sqlite:////out/test.db -e TIKTOKEN_CACHE_DIR=/tiktoken -e HF_HUB_OFFLINE=1 \
    -e PYTHONUNBUFFERED=1 -e PYTHONPATH=/site:/tmp/up -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp youtu-upstream sh -c '
set -e
# step LOG УСЛОВИЕ команда...: команда в фоне с выводом в /out/LOG; ждёт УСЛОВИЯ, потом гасит процесс
step() {
    log=$1 done=$2
    shift 2
    "$@" > "/out/$log" 2>&1 &
    pid=$!
    until eval "$done"; do
        if ! kill -0 $pid 2>/dev/null; then
            eval "$done" && break
            echo "$log: процесс вышел без результата"
            exit 1
        fi
        sleep 5
    done
    sleep 5
    if kill $pid 2>/dev/null; then
        echo "$log: результат есть, повисший процесс погашен"
    else
        echo "$log: результат есть, процесс вышел сам"
    fi
    wait $pid || true
}
# logs/ в дереве апстрима — от прошлых запусков на хосте
cp -r /up /tmp/up && rm -rf /tmp/up/logs && cp -r /cfg/. /tmp/up/configs/ && cd /tmp/up
step train.log "[ -s configs/agents/practice/tf_live_agent.yaml ]" \
    python scripts/run_training_free_GRPO.py --config_name math_live --experiment_name tf_live \
    --batch_size 4 --grpo_n 3 --rollout_concurrency 1 --rollout_data_truncate 16
cp configs/agents/practice/tf_live_agent.yaml /out/
mv logs /out/utu_train
step test.log "grep -qF \"> Cleaning up...\" logs/utu.log* 2>/dev/null" python scripts/run_eval.py --config_name math/math_live_test
mv logs /out/utu_test' 2>&1 | tee "$OUT/run.log"
mv "$OUT/rec/rec.jsonl" "$OUT/rec.jsonl" && rmdir "$OUT/rec"
