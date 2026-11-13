#!/bin/bash
# EV13: оценщик 27B NT, подача EV12 + свёртка расхождений до шага 1, набор из 10 правок по разным проблемам
cd /Users/user/Projects/nrhsi
S=/private/tmp/claude-501/-Users-user-Projects-itmo/0b27b398-da99-461f-b5a5-02754fadcd5d/scratchpad
D=runs/evset_1113/set
for k in 00 01 03 04 05 06 07 09 t4 14; do
  v=$(python3 -c "import json;i=json.load(open('$D/${k}_items.json'))[0];print(i['view'],i['bench'],i['obs'])")
  set -- $v
  python3 probes/1112/ev_judge.py $D/${k}_items.json --states $D/${k}_states.jsonl --obs runs/typed_1111/in/$3.txt \
    --view runs/full_1112/$1 --bench $2 --work $S/chk_$1 --stand plain27 --blocks --win 6,0 --sparse --v2 --prompt runs_v2 --out $D/plain27_v2.jsonl
  echo "$(date +%H:%M:%S) $k $(tail -n 1 $D/plain27_v2.jsonl | python3 -c 'import json,sys;d=json.loads(sys.stdin.read());print(d["label"],d["verdict"],d["where_run"],d["where_call"],d["sec"])')"
done
echo "ALL done $(date +%H:%M)"
