#!/bin/bash
# запись DC с исполнением кода (по умолчанию апстрима): апстрим целиком в контейнере dc-upstream (образ —
# ../dc_code/Dockerfile), сеть — внутренняя dcnet без выхода наружу, единственный выход — контейнер записи dcrec
# (tools/record, --seed) к шлюзу на хосте. sitecustomize.py задаёт сид имён tempfile.
# usage: run.sh OUT [APPROACH [CHEATSHEET_PROMPT]]   (по умолчанию DC-Cu; OUT/rec.jsonl — запись,
# OUT/outputs.jsonl — выход апстрима, OUT/run.log — его вывод)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
APPROACH=${2:-DynamicCheatsheet_Cumulative}
CS=${3-prompts/curator_prompt_for_dc_cumulative.txt}
HERE=$(cd "$(dirname "$0")" && pwd)
U=${UPSTREAMS:-$HOME/Projects/upstreams}
ACE=${ACE:-$(cd "$HERE/../../.." && pwd)}
mkdir -p "$OUT/rec" "$OUT/results"
docker network inspect dcnet >/dev/null 2>&1 || docker network create --internal dcnet >/dev/null
docker run -d --rm --name dcrec --network bridge -v "$ACE/tools":/ace/tools:ro -v "$OUT/rec":/out -e PYTHONPATH=/ace \
    -e PYTHONDONTWRITEBYTECODE=1 dc-upstream python -c "
from pathlib import Path
from tools.record.record import Recorder
Recorder(('0.0.0.0', 8080), Path('/out/rec.jsonl'), '${MODEL_URL:-http://host.docker.internal:8080}', None, True).serve_forever()" >/dev/null
docker network connect dcnet dcrec
trap 'docker rm -f dcrec >/dev/null' EXIT
docker run --rm --name dcrun --network dcnet --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 \
    --memory 4g -v "$U/dynamic-cheatsheet":/up:ro -v "$U/.tiktoken":/tiktoken:ro -v "$OUT/results":/out \
    -v "$HERE/sitecustomize.py":/site/sitecustomize.py:ro -w /up \
    -e OPENAI_BASE_URL=http://dcrec:8080/v1 -e OPENAI_API_KEY=x -e TIKTOKEN_CACHE_DIR=/tiktoken -e HF_HUB_OFFLINE=1 \
    -e HF_DATASETS_OFFLINE=1 -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp -e PYTHONPATH=/site dc-upstream \
    python run_benchmark.py --task MathEquationBalancer --approach_name "$APPROACH" \
      --model_name openai/ornith15-9b --generator_prompt_path prompts/generator_prompt.txt \
      ${CS:+--cheatsheet_prompt_path "$CS"} --max_n_samples 5 --save_directory /out 2>&1 | tee "$OUT/run.log"
mv "$OUT/rec/rec.jsonl" "$OUT/rec.jsonl" 2>/dev/null || true
mv "$OUT"/results/MathEquationBalancer/*/*.jsonl "$OUT/outputs.jsonl"
rm -rf "$OUT/rec" "$OUT/results"
