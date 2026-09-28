#!/bin/bash
# общий раннер записей DC с любыми аргументами run_benchmark.py; окружение — как у ../dc_code_v2/run.sh: апстрим
# целиком в контейнере dc-upstream (образ — ../dc_code_v2/Dockerfile), сеть — внутренняя dcnet без выхода наружу,
# единственный выход — контейнер записи dcrec (tools/record) к шлюзу; ../dc_code_v2/sitecustomize.py — сид tempfile.
# Бенчмарк и срез у всех записей DC одни: MathEquationBalancer, 5 вопросов. --execute_python_code у Tap при
# умолчании True выключает исполнение кода (записи *_nocode).
# usage: run.sh OUT ARGS...   (ARGS — остальные аргументы run_benchmark.py: подход, промпт куратора, флаг кода;
# OUT/rec.jsonl — запись, OUT/outputs.jsonl и OUT/params.json — выход апстрима, OUT/run.log — его вывод)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
shift
HERE=$(cd "$(dirname "$0")" && pwd)
U=${UPSTREAMS:-$HOME/Projects/upstreams}
ACE=${ACE:-$(cd "$HERE/../.." && pwd)}
mkdir -p "$OUT/rec" "$OUT/results"
docker network inspect dcnet >/dev/null 2>&1 || docker network create --internal dcnet >/dev/null
docker run -d --rm --name dcrec --network bridge -v "$ACE/tools":/ace/tools:ro -v "$OUT/rec":/out -e PYTHONPATH=/ace \
    -e PYTHONDONTWRITEBYTECODE=1 dc-upstream python -c "
from pathlib import Path
from tools.record.record import Recorder
Recorder(('0.0.0.0', 8080), Path('/out/rec.jsonl'), '${MODEL_URL:-http://host.docker.internal:8080}').serve_forever()" >/dev/null
docker network connect dcnet dcrec
trap 'docker rm -f dcrec >/dev/null' EXIT
docker run --rm --name dcrun --network dcnet --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 \
    --memory 4g -v "$U/dynamic-cheatsheet":/up:ro -v "$U/.tiktoken":/tiktoken:ro -v "$OUT/results":/out \
    -v "$HERE/../dc_code_v2/sitecustomize.py":/site/sitecustomize.py:ro -w /up \
    -e OPENAI_BASE_URL=http://dcrec:8080/v1 -e OPENAI_API_KEY=x -e TIKTOKEN_CACHE_DIR=/tiktoken -e HF_HUB_OFFLINE=1 \
    -e HF_DATASETS_OFFLINE=1 -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp -e PYTHONPATH=/site dc-upstream \
    python run_benchmark.py --task MathEquationBalancer --model_name openai/ornith15-9b \
      --generator_prompt_path prompts/generator_prompt.txt --max_n_samples 5 --save_directory /out "$@" \
      2>&1 | tee "$OUT/run.log"
mv "$OUT/rec/rec.jsonl" "$OUT/rec.jsonl" 2>/dev/null || true
mv "$OUT"/results/MathEquationBalancer/*/*_params.json "$OUT/params.json"
mv "$OUT"/results/MathEquationBalancer/*/*.jsonl "$OUT/outputs.jsonl"
rm -rf "$OUT/rec" "$OUT/results"
