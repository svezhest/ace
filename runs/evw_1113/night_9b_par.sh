#!/bin/bash
# 17.11 (EV27, автор: «по прикидкам какая лучше такую и выбери… производительность на максимуме»): писатель 9B NT и T
# с check, 4 потока по входам; пара NT → T одного входа — в одном потоке. Рядом доснимается EV28 eval9t.
# Стенд — probes/1117/stand9p.sh. Запуск — когда llm-81 освободит GPU (файл ~/Projects/llm/logs/GPU_FREE.txt, «model processes left: none»).
M=/Users/user/Projects/nrhsi; H=$M/runs/evw_1113; T=$M/runs/typed_1111; W=/Users/user/Projects/nrhsi-wc
G=/Users/user/Projects/llm/logs/GPU_FREE.txt
until [ -f $G ]; do sleep 60; done
grep -q "model processes left: none" $G || { echo "$(date +%H:%M:%S) GPU_FREE без «none»: $(tr '\n' ' ' < $G)"; exit 1; }
echo "$(date +%H:%M:%S) GPU free: $(tr '\n' ' ' < $G | cut -c1-200)"
bash $M/probes/1117/stand9p.sh || exit 1
(cd $M && python3 probes/1117/ev28.py eval9t >> $H/ev28_eval9t.out 2>&1; echo "$(date +%H:%M:%S) EV28 eval9t done") &
one() {   # $1 вход
  k=$1
  case $k in 00) b=alf; v=alf_n4; i=00_v_rr;; 01) b=app; v=app_r1; i=01_v_rr;; 03) b=app; v=app_r1; i=03_v_rr;;
    04) b=app; v=app_r4; i=04_v_rr;; 05) b=app; v=app_r4; i=05_v_rr;; 06) b=alf; v=alf_r1; i=06_v_rr;;
    07) b=alf; v=alf_r4chk; i=07_v_rr;; 09) b=app; v=app_n2; i=09_v_rr;; t4) b=app; v=app_r1; i=t4;; 14) b=app; v=app_n2; i=14_real;; esac
  for pair in "c9n default" "c9t thinking"; do
    set -- $pair; tag=${k}_$1_s1
    [ -f "$H/logs/$tag.jsonl" ] && grep -q '"type": "end"' "$H/logs/$tag.jsonl" && continue
    (cd $W && python3 -m nrhsi.editor --bench $b --view $T/$v --input-text $T/in/$i.txt --tag $tag --home $H --seed 1 \
      --stand $2 --lint $M/editor/lint) > $H/$tag.out 2>&1
    echo "$(date +%H:%M:%S) $tag $(tail -n 1 $H/$tag.out | cut -c1-200)"
  done
}
for lane in "00 05 t4" "01 06 14" "03 07" "04 09"; do
  (for k in $lane; do one $k; done) &
  sleep 30
done
wait
echo "$(date +%H:%M:%S) NIGHT9B_PAR DONE"
