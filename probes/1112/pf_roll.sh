#!/bin/bash
# pf_roll.sh [N=10] — проба PF: развилка на ходу 25 сессии runs/n27_1111/logs/t1_plain27t_s1.jsonl (сразу после ответа
# проверки на первую правку, задевшую удачные 8 и 20), по N ответов на плечо, до ответа проверки на следующую правку.
# base — код feature/check-keep-passed («Failed: this edit changes run 8…»), pf — feature/passed-fact (та же строка и
# три вызова лога перед местом расхождения). В обоих плечах история проиграна своим харнессом (--replayed).
M=/Users/user/Projects/nrhsi; T=$M/runs/typed_1111; n=${1:-10}; H=$M/runs/pf_1112; mkdir -p $H
A=(--bench app --view $T/app_r1 --input-text $T/in/t1.txt --ticket $M/docs/tickets_1111/t1.json --home $H --seed 1 --stand plain27t --lint $M/editor/lint)
L=$M/runs/n27_1111/logs/t1_plain27t_s1.jsonl
for arm in pf:pf base:check-keep; do
  a=${arm%%:*}; w=${arm##*:}
  cd $M-wt/$w && python3 editor/roll.py $L --turn 25 --n $n --stop checked --max-turns 4 --replayed --out $H/t1_$a.jsonl -- "${A[@]}" --tag t1_$a > $H/t1_$a.out 2>&1
  echo "$(date +%H:%M:%S) $a $(git rev-parse --short HEAD) $(tail -n 1 $H/t1_$a.out | cut -c1-100)"
done
