#!/bin/bash
# 17.11: переход стенда 9B на stand9d (без batch-invariant, с драфтером) на ближайшей границе пары входов.
# Очередь night_9b.sh снята; идущая 00_c9n_s1 (pid 78623) доходит, затем 00_c9t_s1 — на прежнем стенде, чтобы пара 00
# была на одном стенде; потом остановить EV28, поднять stand9d, продолжить очередь и EV28.
M=/Users/user/Projects/nrhsi; H=$M/runs/evw_1113; T=$M/runs/typed_1111; W=/Users/user/Projects/nrhsi-wc
while kill -0 78623 2>/dev/null; do sleep 15; done
echo "$(date +%H:%M:%S) 00_c9n_s1 $(tail -n 1 $H/00_c9n_s1.out | cut -c1-200)"
if ! { [ -f $H/logs/00_c9t_s1.jsonl ] && grep -q '"type": "end"' $H/logs/00_c9t_s1.jsonl; }; then
  (cd $W && python3 -m nrhsi.editor --bench alf --view $T/alf_n4 --input-text $T/in/00_v_rr.txt --tag 00_c9t_s1 --home $H --seed 1 \
    --stand thinking --lint $M/editor/lint) > $H/00_c9t_s1.out 2>&1
  echo "$(date +%H:%M:%S) 00_c9t_s1 $(tail -n 1 $H/00_c9t_s1.out | cut -c1-200)"
fi
pkill -f "probes/1117/ev28.py"; sleep 2
bash $M/probes/1117/stand9d.sh || exit 1
grep -n "QWEN_DRAFT\|dflash" $M/runs/stand_1111/worker9.log | tail -2
cd $M
for s in eval9 eval9t; do nohup python3 probes/1117/ev28.py $s >> $H/ev28_$s.out 2>&1 & done
NOSTAND=1 bash $H/night_9b.sh
