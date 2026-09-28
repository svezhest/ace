#!/bin/bash
# запись ACE без ground truth: протокол ace_offline_finer (офлайн finer, срез 10/10/10, 2 эпохи) и флаг апстрима
# --no_ground_truth — рефлектор и куратор получают промпты *_NO_GT. Модель — через прокси записи (tools/record);
# адрес и random.seed(0) — sitecustomize.py (utils.py апстрима зашивает api.openai.com).
# usage: run.sh OUT   (OUT/rec.jsonl — запись, OUT/out — выход апстрима (playbook-и, результаты), OUT/run.log — вывод)
set -euo pipefail
OUT=$(mkdir -p "$1" && cd "$1" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
ACE=${ACE:-$(cd "$HERE/../.." && pwd)}
U=${UPSTREAMS:-$ACE/upstreams}
PORT=${PORT:-8096}
W=$OUT/.work
D=$U/ace/eval/finance/data
mkdir -p "$W/eval/finance/data" "$W/site"
cp "$HERE/sitecustomize.py" "$W/site/"
head -10 "$D/finer_train_batched_1000_samples.jsonl" > "$W/eval/finance/data/finer_train10.jsonl"
head -10 "$D/finer_val_batched_500_samples.jsonl" > "$W/eval/finance/data/finer_val10.jsonl"
head -10 "$D/finer_test_subset_006_seed42.jsonl" > "$W/eval/finance/data/finer_test10.jsonl"
echo '{"finer": {"train_data": "./eval/finance/data/finer_train10.jsonl", "val_data": "./eval/finance/data/finer_val10.jsonl", "test_data": "./eval/finance/data/finer_test10.jsonl"}}' \
    > "$W/eval/finance/data/sample_config.json"
(cd "$ACE" && exec .venv/bin/python -m tools.record.record "$OUT/rec.jsonl" --port $PORT \
    --upstream "${MODEL_URL:-http://localhost:8080}") &
trap "kill $!" EXIT
for i in $(seq 60); do (exec 3<>/dev/tcp/127.0.0.1/$PORT) 2>/dev/null && break; sleep 1; done
cd "$W"
PYTHONPATH=$W/site:$U/ace ACE_BASE_URL=http://127.0.0.1:$PORT/v1 OPENAI_API_KEY=x TIKTOKEN_CACHE_DIR=$U/.tiktoken \
    HF_HUB_OFFLINE=1 PYTHONHASHSEED=0 PYTHONUNBUFFERED=1 "$U/.venvs/ace/bin/python" -m eval.finance.run \
    --task_name finer --mode offline --save_path "$OUT/out" --api_provider openai --generator_model ornith15-9b \
    --reflector_model ornith15-9b --curator_model ornith15-9b --test_workers 1 --eval_steps 10 --num_epochs 2 \
    --save_steps 1 --no_ground_truth 2>&1 | tee "$OUT/run.log"
