#!/bin/bash
# wt.sh ДЕРЕВО ВХОД STAND [SEED=1] [HOME=runs/bl_1112] — одна сессия писателя кодом из рабочего дерева ветки
# (~/Projects/nrhsi-wt/ДЕРЕВО; «main» — само ~/Projects/nrhsi, ветка develop). Виды, входы и результаты — в основном дереве.
# ВХОД: t1..t5 (тикеты за 9B о run 1), k10 (отчёт о run 32), 01, 08 (рукописные). Тег — ВХОД_ДЕРЕВО_STAND_sSEED.
M=/Users/user/Projects/nrhsi; T=$M/runs/typed_1111
W=$M-wt/$1; [ "$1" = main ] && W=$M
nn=$2; STAND=$3; s=${4:-1}; H=${5:-$M/runs/bl_1112}; mkdir -p $H
case $nn in
  t[1-5]) b=app; v=app_r1; in=$T/in/$nn.txt; tk=$M/docs/tickets_1111/$nn.json;;
  t1c) b=app; v=app_r1; in=$M/docs/tickets_1112/t1c.txt; tk=$M/docs/tickets_1112/t1c.json;;   # проба CI: № 1 + шаги задетых удачных прогонов
  k10) b=alf; v=alf_n4; in=$T/in/10_real.txt; tk=$M/docs/tickets_1111/k10.json;;
  01) b=app; v=app_r1; in=$T/in/01_v_rr.txt; tk=$M/docs/tickets_1106k/01.json;;
  08) b=alf; v=alf_r1; in=$T/in/08_v_rr.txt; tk=$M/docs/tickets_1106k/08.json;;
  *) echo "неизвестный вход $nn"; exit 1;;
esac
tag=${nn}_$1_${STAND}_s$s
cd $W || exit 1
python3 -m nrhsi.editor --bench $b --view $T/$v --input-text $in --ticket $tk --tag $tag --home $H --seed $s \
  --stand $STAND --lint $M/editor/lint > $H/$tag.out 2>&1
echo "$(date +%H:%M:%S) $tag $(git -C $W rev-parse --short HEAD) $(tail -n 1 $H/$tag.out | cut -c1-150)"
