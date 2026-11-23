#!/bin/bash
# 24.11 RV2: исследователь по одному прогону (ветка feature/researcher-per-run, nrhsi-wt/per-run) — 9B T s1–2 (40 сессий, 14 параллельно), затем 27B NT s1 (20 подряд).
M=/Users/user/Projects/nrhsi; W=/Users/user/Projects/nrhsi-wt/per-run; H=$M/runs/res_1124/rv2; mkdir -p $H/9b $H/27b
G=/Users/user/Projects/llm/logs/GPU_FREE.txt; O=/Users/user/Projects/llm/logs/GPU_OWNER.txt
S='qwen-gateway|python3? worker.py'
VIEWS="r1-4-11-24-40_final_s7_r3alf_final:1,4,11,24,40 r4-6-10-23-36_final_s9_r5alf_chk:4,6,10,23,36 r1-4-9-13-19_final_s7_r5app_final:1,4,9,13,19 r4-6-7-12-18_final_s9_r7app_final:4,6,7,12,18"
until [ -f $G ] && grep -qE "model processes left: none" $G && ! pgrep -f "$S" > /dev/null; do sleep 60; done
rm -f $G; echo "nrhsi (RV2: исследователь по прогону — 9B stand9q, затем 27B stand27c), с $(date '+%d.%m %H:%M'), примерно на 4–5 ч" > $O
echo "$(date +%H:%M:%S) branch $(git -C $W rev-parse --short HEAD)"
JOBS=$H/jobs9.txt; : > $JOBS
for s in 1 2; do for v in $VIEWS; do for r in $(echo ${v##*:} | tr , ' '); do echo "${v%%:*} $r $s" >> $JOBS; done; done; done
one() {  # view run seed stand dir
  local t=${1%%_*}_run$2_s$3
  (cd $W && python3 -m nrhsi.researcher --home $H/$5 --view $M/researcher/views/$1 --runs $2 --policy final --stand $4 --seed $3 --tag $5_$t < /dev/null > $H/$5/$t.out 2>&1)
  echo "$(date +%H:%M:%S) $5 $t rc=$?"
}
export -f one; export M W H
bash $M/probes/1119/stand9q.sh || exit 1
xargs -P 14 -L 1 bash -c 'one $0 $1 $2 res9t 9b' < $JOBS
echo "$(date +%H:%M:%S) 9B done"
bash $M/probes/1120/stand27c.sh || exit 1
grep ' 1$' $JOBS | while read v r s; do one $v $r 1 res27 27b; done
echo "$(date +%H:%M:%S) RV2 DONE"
p=$(pgrep -f "$S"); [ -n "$p" ] && kill $p
for i in $(seq 60); do pgrep -f "$S" > /dev/null || break; sleep 1; done
if pgrep -f "$S" > /dev/null || lsof -iTCP:50051 -sTCP:LISTEN > /dev/null 2>&1; then
  echo "$(date +%H:%M:%S) stand did not stop, GPU not released"
else
  rm -f $O
  printf "nrhsi RV2 finished %s, stand stopped\nmodel processes left: none\n" "$(date '+%Y-%m-%d %H:%M:%S')" > $G
  echo "$(date +%H:%M:%S) GPU released"
fi
