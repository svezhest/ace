#!/bin/bash
# stand27a.sh (20.11: набор A — без драфтеров; на наборе B своп 3 ГиБ за 3 мин при подъёме EV37) — поднять стенд 27B заново (профили stands/think27.json — шлюз 8091, и plain27.json — шлюз 8092 без рассуждения): остановить воркер и шлюзы, запустить, дождаться ответа.
# Зачем заново: кэш промпта прошлой сессии остаётся в памяти воркера (до 6 ГБ), и вторая-третья сессия подряд может
# упасть на prefill с «[METAL] Insufficient Memory» (11.11 15:40, t3 после 01 и t5). Перезапуск между сессиями это снимает.
L=/Users/user/Projects/nrhsi/runs/stand_1111; mkdir -p $L
p=$(pgrep -f 'qwen-gateway|python3? worker.py'); [ -n "$p" ] && kill $p
for i in $(seq 60); do pgrep -f 'qwen-gateway|python3? worker.py' > /dev/null || break; sleep 1; done
# 13.11: воркер не всегда выходит по SIGTERM — тогда новый воркер падал по памяти рядом со старым; добиваем и проверяем порт
p=$(pgrep -f 'qwen-gateway|python3? worker.py'); [ -n "$p" ] && { kill -9 $p; sleep 2; }
lsof -iTCP:50051 -sTCP:LISTEN > /dev/null 2>&1 && { echo "$(date +%H:%M:%S) port 50051 still busy, not starting"; exit 1; }
cd /Users/user/Projects/llm/src/worker
# 18.11: рецепт llm-81, набор B (main 2df454b): q8 KV, предел 24 ГиБ, драфтеры auto (автор: «ну вроде можно с драфтером»). Замер 70K писателя + 40K оценщика:
# пик 22,6 ГиБ (1,4 под пределом), декод на 70K 14 ток/с. С драфтерами (набор B) пик 24,1 — в упор к пределу, своп ~5 ГиБ.
# Набор A — то же без QWEN_DRAFT. Проверка: в worker27.log «KV budget 3.86 GiB (cap 24.0 GiB…)». Автор не дома и запас
# памяти на практике не проверял: после первого подъёма смотреть vm_stat/memory_pressure и вернуть A, если будет своп.
# Окружение должно совпадать с stands/*27*.json ключ в ключ: stand.check() сравнивает его целиком.
HF_HUB_OFFLINE=1 QWEN_MODEL=../../weights/qwen38-27b-mlx-oq4e QWEN_TEXT_ONLY=1 QWEN_MRQMM4=1 QWEN_MRQMM5=1 QWEN_MRQMM6=1 QWEN_KV_BITS=8 QWEN_KVQ_PREFILL_FUSED=1 QWEN_DECODE_ATT=8192 QWEN_MAX_BATCH=1 QWEN_MAX_CONTEXT=98304 QWEN_PROMPT_CACHE=1 QWEN_PROMPT_CACHE_MOVE=1 QWEN_PROMPT_CACHE_GB=6 QWEN_PROMPT_CACHE_CKPTS=4 QWEN_PREFILL_RESERVE_GB=2.5 QWEN_WIRED_LIMIT_GB=24 QWEN_CACHE_LIMIT_GB=1 QWEN_SDPA_FUSED_MIN_KV=8192 QWEN_PREFILL_BUDGET=16777216 QWEN_PRESENCE_PENALTY=0 \
  nohup uv run python worker.py >> $L/worker27.log 2>&1 &
cd /Users/user/Projects/llm
for i in $(seq 120); do lsof -iTCP:50051 -sTCP:LISTEN > /dev/null 2>&1 && break; sleep 2; done
GATEWAY_ADDR=127.0.0.1:8091 GATEWAY_SERVED_MODEL_NAMES=qwen38-27b nohup ./target/release/qwen-gateway >> $L/gateway27.log 2>&1 &
GATEWAY_ADDR=127.0.0.1:8092 GATEWAY_THINKING=off GATEWAY_SERVED_MODEL_NAMES=qwen38-27b nohup ./target/release/qwen-gateway >> $L/gateway27n.log 2>&1 &
for i in $(seq 120); do
  curl -s -m 120 http://127.0.0.1:8091/v1/chat/completions -H 'content-type: application/json' \
    -d '{"model":"qwen38-27b","messages":[{"role":"user","content":"Say ok"}],"max_tokens":8,"temperature":0}' | grep -q '"choices"' \
    && { echo "$(date +%H:%M:%S) stand27 up"; exit 0; }
  sleep 3
done
echo "$(date +%H:%M:%S) stand27 did not come up"; exit 1
