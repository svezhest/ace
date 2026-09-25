#!/bin/bash
# запись DC с исполнением кода: апстрим целиком в контейнере dc-upstream (код модели исполняется только там),
# сеть — внутренняя dcnet без выхода наружу; единственный выход — контейнер записи dcrec (tools/record) к шлюзу
# на хосте. usage: run.sh OUT   (OUT/rec/rec.jsonl — запись, OUT/results — выход апстрима; модель пишет только туда)
set -eu
OUT=$(cd "$1" && pwd)
mkdir -p "$OUT/rec" "$OUT/results"
U=${UPSTREAMS:-/Users/user/Projects/upstreams}
ACE=${ACE:-/Users/user/Projects/ace}
docker network inspect dcnet >/dev/null 2>&1 || docker network create --internal dcnet >/dev/null
docker run -d --rm --name dcrec --network bridge -v "$ACE/tools":/ace/tools:ro -v "$OUT/rec":/out -e PYTHONPATH=/ace \
    -e PYTHONDONTWRITEBYTECODE=1 dc-upstream python -c "
from pathlib import Path
from tools.record.record import Recorder
Recorder(('0.0.0.0', 8080), Path('/out/rec.jsonl'), 'http://host.docker.internal:8080', None, True).serve_forever()" >/dev/null
docker network connect dcnet dcrec
trap 'docker rm -f dcrec >/dev/null' EXIT
docker run --rm --name dcrun --network dcnet --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 \
    --memory 4g -v "$U/dynamic-cheatsheet":/up:ro -v "$U/.tiktoken":/tiktoken:ro -v "$OUT/results":/out -w /up \
    -e OPENAI_BASE_URL=http://dcrec:8080/v1 -e OPENAI_API_KEY=x -e TIKTOKEN_CACHE_DIR=/tiktoken -e HF_HUB_OFFLINE=1 \
    -e HF_DATASETS_OFFLINE=1 -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp dc-upstream \
    python run_benchmark.py --task MathEquationBalancer --approach_name DynamicCheatsheet_Cumulative \
      --model_name openai/ornith15-9b --generator_prompt_path prompts/generator_prompt.txt \
      --cheatsheet_prompt_path prompts/curator_prompt_for_dc_cumulative.txt --max_n_samples 5 \
      --save_directory /out
