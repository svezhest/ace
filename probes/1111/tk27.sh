#!/bin/bash
# tk27.sh ВХОД STAND — сессия писателя на локальном стенде по входу за авторством 9B:
#   t1..t5 — правдоподобные тикеты о run 1 (вид app_r1, тикет docs/tickets_1111/tN.json);
#   k10    — настоящий отчёт ревьювера о run 32 (вид alf_n4, вход 10_real, тикет docs/tickets_1111/k10.json).
# Тег сессии — ВХОД_STAND_s1, каталог runs/n27_1111.
cd /Users/user/Projects/nrhsi; T=$PWD/runs/typed_1111
case $1 in
  t[1-5]) b=app; v=app_r1; in=$T/in/$1.txt;;
  k10) b=alf; v=alf_n4; in=$T/in/10_real.txt;;
esac
tag=$1_$2_s1
python3 -m nrhsi.editor --bench $b --view $T/$v --input-text $in --ticket docs/tickets_1111/$1.json --tag $tag \
  --home runs/n27_1111 --seed 1 --stand $2 --lint $PWD/editor/lint > runs/n27_1111/$tag.out 2>&1
echo "$(date +%H:%M:%S) $tag $(tail -n 1 runs/n27_1111/$tag.out | cut -c1-160)"
