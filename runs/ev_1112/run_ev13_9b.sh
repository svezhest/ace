#!/bin/bash
# EV13: ждёт PID запуска EV12 на 27B; затем EV6a на 27B; затем стенд 9B и та же пара подач на 9B NT (eval9) и 9B T (eval9t)
cd /Users/user/Projects/nrhsi
SC=/private/tmp/claude-501/-Users-user-Projects-itmo/0b27b398-da99-461f-b5a5-02754fadcd5d/scratchpad
while kill -0 $1 2>/dev/null; do sleep 15; done
bash runs/ev_1112/run_ev13a.sh > runs/ev_1112/run_ev13a.out 2>&1; echo "27B EV6a done $(date +%H:%M)"
bash probes/1111/stand9.sh || exit 1
for st in eval9 eval9t; do
  for f in run_ev13 run_ev13a; do
    sed "s/--stand plain27/--stand $st/; s/plain27_/${st}_/g" runs/ev_1112/$f.sh > $SC/${f}_$st.sh
    bash $SC/${f}_$st.sh > runs/ev_1112/${f}_$st.out 2>&1; echo "$st $f done $(date +%H:%M)"
  done
done
echo "ALL done $(date +%H:%M)"
