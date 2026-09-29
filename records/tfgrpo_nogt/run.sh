#!/bin/bash
# запись TF-GRPO без ground truth: протокол records/tfgrpo (там же подробности: данные, контейнеры, рандом, часы,
# гашение повисших процессов) и штатный переключатель апстрима practice.given_ground_truth: false
# (configs/practice/math_live_nogt.yaml). Тогда в итоге rollout и в групповом преимуществе вместо эталона и награды —
# [REDACTED], и извлекаются все группы, а не только частично верные (utu/practice/experience_updater.py).
# prep.py, Dockerfile, sitecustomize.py и конфиги — из records/tfgrpo; контейнеры — свои (tfng-rec, tfng-run).
# usage: [TFGRPO_ALL_TASKS=1] run.sh OUT [CACHE]   (CACHE — прошлая запись этого раннера, можно .gz: её ответы прокси
# отдаёт без модели, tools/record/record.py; TFGRPO_ALL_TASKS=1 — без исключения задачи в prep.py; в OUT то же, что у records/tfgrpo)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
CACHE=${2:+$(cd "$(dirname "$2")" && pwd)/$(basename "$2")}
if [[ $CACHE == *.gz ]]; then
    gunzip -c "$CACHE" > "$OUT/cache.jsonl"
    CACHE=$OUT/cache.jsonl
fi
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(cd "$HERE/../tfgrpo" && pwd)
ACE=${ACE:-$(cd "$HERE/../.." && pwd)}
U=${UPSTREAMS:-$ACE/upstreams}
mkdir -p "$OUT/rec" "$OUT/prep/data"
ln -s "$U/.data/DAPO-Math-17k" "$OUT/prep/data/"
UTU_LLM_TYPE=chat.completions UTU_LLM_MODEL=x UTU_LLM_BASE_URL=http://127.0.0.1:9/v1 UTU_LLM_API_KEY=x \
    UTU_DB_URL=sqlite:///$OUT/test.db HF_HOME=$U/.hf HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 UPSTREAMS=$U \
    "$U/.venvs/youtu/bin/python" "$T/prep.py" "$OUT/prep" > "$OUT/prep.log" 2>&1
rm -rf "$OUT/prep"
M=ornith15-9b
docker build -q -t youtu-upstream "$T" >/dev/null
docker network inspect tfnet >/dev/null 2>&1 || docker network create --internal tfnet >/dev/null
docker run -d --rm --name tfng-rec --network bridge -v "$ACE/tools":/ace/tools:ro -v "$OUT/rec":/out -e PYTHONPATH=/ace \
    ${CACHE:+-v "$CACHE":/cache.jsonl:ro} \
    -e PYTHONDONTWRITEBYTECODE=1 youtu-upstream python -c "
from pathlib import Path
from tools.record.record import Recorder
Recorder(('0.0.0.0', 8080), Path('/out/rec.jsonl'), '${MODEL_URL:-http://host.docker.internal:8080}',
         cache=Path('/cache.jsonl') if Path('/cache.jsonl').is_file() else None).serve_forever()" >/dev/null
docker network connect tfnet tfng-rec
trap 'docker rm -f tfng-rec >/dev/null' EXIT
docker run --rm --name tfng-run --network tfnet --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 \
    --memory 8g -v "$U/youtu-agent":/up:ro -v "$T/configs":/cfg:ro -v "$HERE/configs":/cfg_nogt:ro \
    -v "$U/.tiktoken":/tiktoken:ro -v "$OUT":/out \
    -v "$T/sitecustomize.py":/site/sitecustomize.py:ro -e PYTHONHASHSEED=0 -e FAKETIME="2026-01-01 00:00:00" \
    -e FAKETIME_DONT_FAKE_MONOTONIC=1 -e LD_PRELOAD=/usr/local/lib/libfaketimeMT.so.1 \
    -e UTU_LLM_TYPE=chat.completions -e UTU_LLM_MODEL=$M -e UTU_LLM_BASE_URL=http://tfng-rec:8080/v1 -e UTU_LLM_API_KEY=x \
    -e JUDGE_LLM_TYPE=chat.completions -e JUDGE_LLM_MODEL=$M -e JUDGE_LLM_BASE_URL=http://tfng-rec:8080/v1 \
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
cp -r /up /tmp/up && rm -rf /tmp/up/logs && cp -r /cfg/. /cfg_nogt/. /tmp/up/configs/ && cd /tmp/up
step train.log "[ -s configs/agents/practice/tf_live_agent.yaml ]" \
    python scripts/run_training_free_GRPO.py --config_name math_live_nogt --experiment_name tf_live \
    --batch_size 4 --grpo_n 3 --rollout_concurrency 1 --rollout_data_truncate 16
cp configs/agents/practice/tf_live_agent.yaml /out/
mv logs /out/utu_train
step test.log "grep -qF \"> Cleaning up...\" logs/utu.log* 2>/dev/null" python scripts/run_eval.py --config_name math/math_live_test
mv logs /out/utu_test' 2>&1 | tee "$OUT/run.log"
mv "$OUT/rec/rec.jsonl" "$OUT/rec.jsonl" && rmdir "$OUT/rec"
rm -f "$OUT/cache.jsonl"
