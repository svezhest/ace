#!/bin/bash
# k10.sh on|off TAG [--dry] — писатель на DeepSeek по настоящему отчёту ревьювера о run 32 (ALF, вид alf_n4), тикет без keep
set -a; . /Users/user/Projects/itmo/cs-masters/bluesec/agent/.env; set +a
cd /Users/user/Projects/nrhsi
exec python3 probes/1111/ds/run_ds.py $1 -- --bench alf --view runs/typed_1110/alf_n4 \
  --input-text runs/typed_1110/in/10_real.txt --ticket docs/tickets_1111/k10.json --seed 1 --lint editor/lint \
  --home runs/ds_1111 --tag $2 $3
