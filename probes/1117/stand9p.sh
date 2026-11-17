#!/bin/bash
# stand9p.sh (17.11): стенд 9B для 4 параллельных сессий писателя + оценщик, рецепт llm-81 (22:28): q8 KV, без batch-invariant,
# предел процесса 21 ГиБ (запас памяти ноутбука), драфтер под Ornith для моментов с одной строкой, новый дисковый кэш (не смешивать с fp16). Поднять стенд 9B (профили stands/default.json и thinking.json): остановить воркер и шлюзы, запустить, дождаться ответа.
L=/Users/user/Projects/nrhsi/runs/stand_1111; mkdir -p $L
p=$(pgrep -f 'qwen-gateway|python3? worker.py'); [ -n "$p" ] && kill $p
for i in $(seq 60); do pgrep -f 'qwen-gateway|python3? worker.py' > /dev/null || break; sleep 1; done
# 13.11: воркер не всегда выходит по SIGTERM — тогда новый воркер падал по памяти рядом со старым; добиваем и проверяем порт
p=$(pgrep -f 'qwen-gateway|python3? worker.py'); [ -n "$p" ] && { kill -9 $p; sleep 2; }
lsof -iTCP:50051 -sTCP:LISTEN > /dev/null 2>&1 && { echo "$(date +%H:%M:%S) port 50051 still busy, not starting"; exit 1; }
cd /Users/user/Projects/llm/src/worker
HF_HUB_OFFLINE=1 QWEN_MODEL=../../weights/ornith15-9b-mlx-8bit QWEN_KV_BITS=8 QWEN_MAX_CONTEXT=131072 QWEN_PRESENCE_PENALTY=0 \
  QWEN_PROMPT_CACHE=1 QWEN_PROMPT_CACHE_GB=4 QWEN_PROMPT_CACHE_REPLY=0 QWEN_BATCH_RESERVE_TOKENS=1024 \
  QWEN_PROMPT_CACHE_DISK=/Users/user/.cache/qwen-pcdisk-q8 QWEN_MAX_BATCH=16 \
  QWEN_WIRED_LIMIT_GB=21 QWEN_CACHE_LIMIT_GB=1 \
  QWEN_DRAFT=auto QWEN_DRAFT_DFLASH=../../weights/_staging/ornith15-9b-dflash QWEN_DRAFT_MTP=../../weights/_staging/ornith15-9b-mtp-q8 \
  nohup uv run python worker.py >> $L/worker9.log 2>&1 &
cd /Users/user/Projects/llm
for i in $(seq 120); do lsof -iTCP:50051 -sTCP:LISTEN > /dev/null 2>&1 && break; sleep 2; done
GATEWAY_ADDR=127.0.0.1:8090 GATEWAY_THINKING=off GATEWAY_SERVED_MODEL_NAMES=ornith15-9b,ornith-ai/Ornith-1.5-9B-MLX-8bit \
  nohup ./target/release/qwen-gateway >> $L/gateway9.log 2>&1 &
GATEWAY_ADDR=127.0.0.1:8081 GATEWAY_SERVED_MODEL_NAMES=ornith15-9b,ornith-ai/Ornith-1.5-9B-MLX-8bit \
  nohup ./target/release/qwen-gateway >> $L/gateway9t.log 2>&1 &
for i in $(seq 120); do
  curl -s -m 120 http://127.0.0.1:8090/v1/chat/completions -H 'content-type: application/json' \
    -d '{"model":"ornith15-9b","messages":[{"role":"user","content":"Say ok"}],"max_tokens":8,"temperature":0}' | grep -q '"choices"' \
    && { echo "$(date +%H:%M:%S) stand9 up"; exit 0; }
  sleep 3
done
echo "$(date +%H:%M:%S) stand9 did not come up"; exit 1
