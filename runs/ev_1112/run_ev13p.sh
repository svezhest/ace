#!/bin/bash
# EV13: правки промпта — отдельный оценщик (задача, промпт до и после); логика — без файлов промпта (автор 13.11)
cd /Users/user/Projects/nrhsi
S=/private/tmp/claude-501/-Users-user-Projects-itmo/0b27b398-da99-461f-b5a5-02754fadcd5d/scratchpad
D=runs/evset_1113/set
args() { python3 -c "import json;i=json.load(open('$D/$1_items.json'))[0];print('--view runs/full_1112/'+i['view'],'--bench',i['bench'],'--obs runs/typed_1111/in/'+i['obs']+'.txt','--work $S/chk_'+i['view'])"; }
J="python3 probes/1112/ev_judge.py"
for k in 05 09 t4 14; do
  $J $D/${k}_items_prompt.json --states $D/${k}_states.jsonl $(args $k) --stand plain27 --part prompt --prompt prompt_edit --out $D/plain27_prompt.jsonl
  echo "$(date +%H:%M:%S) prompt $k done"
done
for k in 00 01 03 04 05 06 07 09 t4 14; do
  $J $D/${k}_items.json --states $D/${k}_states.jsonl $(args $k) --stand plain27 --part logic --blocks --win 6,0 --sparse --v2 --prompt runs_v2 --out $D/plain27_v2_logic.jsonl
  $J $D/${k}_items.json --states $D/${k}_states.jsonl $(args $k) --stand plain27 --part logic --blocks --prompt runs --out $D/plain27_runs_logic.jsonl
  echo "$(date +%H:%M:%S) logic $k done"
done
echo "ALL done $(date +%H:%M)"
