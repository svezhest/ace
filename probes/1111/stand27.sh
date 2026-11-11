#!/bin/bash
# stand27.sh — поднять стенд 27B заново (профиль stands/think27.json): остановить воркер и шлюзы, запустить, дождаться ответа.
# Зачем заново: кэш промпта прошлой сессии остаётся в памяти воркера (до 6 ГБ), и вторая-третья сессия подряд может
# упасть на prefill с «[METAL] Insufficient Memory» (11.11 15:40, t3 после 01 и t5). Перезапуск между сессиями это снимает.
L=/Users/user/Projects/nrhsi/runs/stand_1111; mkdir -p $L
p=$(pgrep -f 'qwen-gateway|python3? worker.py'); [ -n "$p" ] && kill $p
for i in $(seq 60); do pgrep -f 'qwen-gateway|python3? worker.py' > /dev/null || break; sleep 1; done
cd /Users/user/Projects/llm/src/worker
HF_HUB_OFFLINE=1 QWEN_MODEL=../../weights/qwen38-27b-mlx-5bit QWEN_DRAFT=../../weights/qwen38-27b-dflash2 QWEN_KV_BITS=0 \
  QWEN_MRQMM5=1 QWEN_MAX_BATCH=1 QWEN_MAX_CONTEXT=65536 QWEN_PROMPT_CACHE=1 QWEN_PROMPT_CACHE_MOVE=1 QWEN_PROMPT_CACHE_GB=3 QWEN_BATCH_MEM_GB=3.2 \
  QWEN_PROMPT_CACHE_CKPTS=4 QWEN_WIRED_LIMIT_GB=27 QWEN_CACHE_LIMIT_GB=1 QWEN_SDPA_FUSED_MIN_KV=8192 \
  QWEN_PREFILL_BUDGET=16777216 QWEN_PRESENCE_PENALTY=0 nohup uv run python worker.py >> $L/worker27.log 2>&1 &
cd /Users/user/Projects/llm
for i in $(seq 120); do lsof -iTCP:50051 -sTCP:LISTEN > /dev/null 2>&1 && break; sleep 2; done
GATEWAY_ADDR=127.0.0.1:8091 GATEWAY_SERVED_MODEL_NAMES=qwen38-27b nohup ./target/release/qwen-gateway >> $L/gateway27.log 2>&1 &
for i in $(seq 120); do
  curl -s -m 120 http://127.0.0.1:8091/v1/chat/completions -H 'content-type: application/json' \
    -d '{"model":"qwen38-27b","messages":[{"role":"user","content":"Say ok"}],"max_tokens":8,"temperature":0}' | grep -q '"choices"' \
    && { echo "$(date +%H:%M:%S) stand27 up"; exit 0; }
  sleep 3
done
echo "$(date +%H:%M:%S) stand27 did not come up"; exit 1
