#!/bin/bash
# 17.11 (EV27): писатель 9B без рассуждения (default) и с ним (thinking), оба с check; оценщик в сессии — 9B с рассуждением,
# подача автора (ветка feature/writer-check-v2, e31b12a). 10 входов × seed 1; NT и T подряд на каждом входе, чтобы при
# остановке сравнение оставалось парным. Стенд 9B поднимается один раз (stand9.sh), 27B не нужен.
# Идемпотентен: сессия с записанным end в logs/ не пересчитывается. На «пауза» — снимать этот скрипт, идущую сессию не трогать.
M=/Users/user/Projects/nrhsi; H=$M/runs/evw_1113; T=$M/runs/typed_1111; W=/Users/user/Projects/nrhsi-wc
[ "${NOSTAND:-0}" = 1 ] || { bash $M/probes/1111/stand9.sh || exit 1; }
for k in 00 01 03 04 05 06 07 09 t4 14; do
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
done
echo "$(date +%H:%M:%S) NIGHT9B DONE"
