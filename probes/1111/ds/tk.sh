#!/bin/bash
# tk.sh N on|off TAG [--dry] — писатель на DeepSeek по тикету № N (вид app_r1c: app_r1 без мёртвой проверки вывода)
set -a; . /Users/user/Projects/itmo/cs-masters/bluesec/agent/.env; set +a
cd /Users/user/Projects/nrhsi
exec python3 probes/1111/ds/run_ds.py $2 -- --bench app --view runs/typed_1111/app_r1c \
  --input-text runs/typed_1111/in/t$1.txt --ticket docs/tickets_1111/t$1.json --seed 1 --lint editor/lint \
  --home runs/ds_1111 --tag $3 $4
