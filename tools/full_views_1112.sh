#!/bin/bash
# full_views_1112.sh — виды runs/typed_1111 со всеми записанными прогонами их узлов (EV0, план EV-evaluator-plan.md).
# src и README — из вида, logs — из узла. В app_r1 нет run 19 (записан до защиты моста, убран по слову автора 11.11).
M=/Users/user/Projects/nrhsi; T=$M/runs/typed_1111; O=$M/runs/full_1112; mkdir -p $O
for pair in app_r1:appworld/views_e3/e4app_diary_s1 app_r4:appworld/views_e3/e8app_cause_s1 \
            alf_r1:alfworld/view_v3 alf_r4chk:alfworld/view_v3 app_n2:runs/tree_app_1101/n2 alf_n4:runs/tree_alf_1101/n4; do
  v=${pair%%:*}; n=$M/${pair#*:}
  rm -rf $O/$v && mkdir -p $O/$v && cp $T/$v/README.md $O/$v/ && cp -R $T/$v/src $O/$v/src && cp -R $n/logs $O/$v/logs
  find $O/$v -name __pycache__ -prune -exec rm -rf {} +
done
rm $O/app_r1/logs/run_19.jsonl
python3 - $O/app_r1/logs/results.jsonl <<'E'
import json, sys
p = sys.argv[1]; rows = [json.loads(l) for l in open(p) if l.strip()]
open(p, "w").write("".join(json.dumps(r) + "\n" for r in rows if r["run"] != 19))
E
for v in $(ls $O); do echo "$v $(ls $O/$v/logs | grep -c run_) (в виде $(ls $T/$v/logs | grep -c run_))"; done
