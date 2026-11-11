#!/bin/bash
# Серия писателя на видах typed_1111 (без run 19 и входа 02). Исполнитель не запускается.
#   bash probes/1111/series.sh HOME STAND PAR SEED... -- NN...
# PAR — сколько сессий разом (у 27B с драфтером воркер держит один поток: PAR=1). Тег сессии — NN_STAND_sSEED.
# Доп. аргументы редактора — в переменной EXTRA.
cd "$(dirname "$0")/../.." || exit 1
H=$1; STAND=$2; PAR=$3; shift 3
SEEDS=(); while [ "$1" != "--" ]; do SEEDS+=("$1"); shift; done; shift
[ $# -eq 0 ] && set -- 00 01 03 04 05 06 07 08 09
T=$PWD/runs/typed_1111
mkdir -p "$H"
one() {
  nn=$1; seed=$2
  case $nn in
    00|10|11) b=alf; v=alf_n4;; 01|03) b=app; v=app_r1;; 04|05) b=app; v=app_r4;; 06|08) b=alf; v=alf_r1;;
    07) b=alf; v=alf_r4chk;; 09|12|13|14) b=app; v=app_n2;;
  esac
  if [ "$nn" -lt 10 ]; then in=$T/in/${nn}_v_rr.txt; tk=$PWD/docs/tickets_1106k/$nn.json; else in=$T/in/${nn}_real.txt; tk=$PWD/docs/tickets_1110n/$nn.json; fi
  tkarg=(); [ -f "$tk" ] && tkarg=(--ticket "$tk")
  tag=${nn}_${STAND}_s$seed
  [ -f "$H/logs/$tag.jsonl" ] && grep -q '"type": "end"' "$H/logs/$tag.jsonl" && return 0     # уже есть — не перезапускать
  python3 -m nrhsi.editor --bench $b --view $T/$v --input-text $in "${tkarg[@]}" --tag $tag --home $H --seed $seed \
    --stand $STAND --lint $PWD/editor/lint $EXTRA > $H/$tag.out 2>&1
  echo "$(date +%H:%M:%S) $tag $(tail -n 1 $H/$tag.out | cut -c1-160)"
}
export -f one; export H STAND T EXTRA
for s in "${SEEDS[@]}"; do for nn in "$@"; do echo "$nn $s"; done; done | xargs -P "$PAR" -L 1 bash -c 'one $0 $1'
date "+end $STAND %H:%M:%S"
