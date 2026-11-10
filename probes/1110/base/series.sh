#!/bin/bash
# Серия базы на видах typed_1110: по одной сессии писателя на вход и стенд. bash probes/1110/base/series.sh HOME STAND SEED [NN...]
# Исполнитель не запускается: проверки в сессии — повтор записанных прогонов.
cd "$(dirname "$0")/../../.." || exit 1
H=$1; STAND=$2; SEED=$3; shift 3
T=$PWD/runs/typed_1110
[ $# -eq 0 ] && set -- 00 01 02 03 04 05 06 07 08 09 10 11 12 13 14
mkdir -p "$H"
for nn in "$@"; do
  case $nn in
    00|10|11) b=alf; v=alf_n4;; 01|02|03) b=app; v=app_r1;; 04|05) b=app; v=app_r4;; 06|08) b=alf; v=alf_r1;;
    07) b=alf; v=alf_r4chk;; 09|12|13|14) b=app; v=app_n2;;
  esac
  if [ "$nn" -lt 10 ]; then in=$T/in/${nn}_v_rr.txt; tk=$PWD/docs/tickets_1106k/$nn.json; else in=$T/in/${nn}_real.txt; tk=$PWD/docs/tickets_1110n/$nn.json; fi
  tkarg=(); [ -f "$tk" ] && tkarg=(--ticket "$tk")
  tag=${nn}_${STAND}_s$SEED
  python3 -m nrhsi.editor --bench $b --view $T/$v --input-text $in "${tkarg[@]}" --tag $tag --home $H/$tag --seed $SEED \
    --stand $STAND --lint $PWD/editor/lint > $H/$tag.out 2>&1 &
done
wait
date "+end $STAND %H:%M:%S"
tail -q -n 1 $H/*_${STAND}_s$SEED.out | cut -c1-200
