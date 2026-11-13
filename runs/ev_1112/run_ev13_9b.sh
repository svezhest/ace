#!/bin/bash
# EV13: стенд 9B, затем раздельная проверка (логика EV12 и EV6a, промпт) на 9B NT и 9B T
cd /Users/user/Projects/nrhsi
bash probes/1111/stand9.sh || exit 1
for st in eval9 eval9t; do bash runs/ev_1112/run_ev13p9.sh $st > runs/ev_1112/run_ev13p_$st.out 2>&1; echo "$st done $(date +%H:%M)"; done
echo "ALL done $(date +%H:%M)"
