#!/bin/bash
# fa_roll.sh [N=3] — проба FA: докаты сессии runs/ck_1112/logs/t1_ck_r0.jsonl с хода 27 (сразу после правки с условием
# `any(s.code == code and s.output == steps[-1].output for s in recent)`, не истинным ни разу), по N на плечо:
# fa — код ветки feature/failed-line-any (строка Failed со счётом по частям any), base — код feature/check-keep-passed.
# В обоих плечах история проиграна своим харнессом (--replayed). Результаты — runs/fa_1112.
M=/Users/user/Projects/nrhsi; T=$M/runs/typed_1111; n=${1:-3}; H=$M/runs/fa_1112; mkdir -p $H
A=(--bench app --view $T/app_r1 --input-text $T/in/t1.txt --ticket $M/docs/tickets_1111/t1.json --home $H --seed 1 --stand plain27t --lint $M/editor/lint)
L=$M/runs/ck_1112/logs/t1_ck_r0.jsonl
for arm in fa:fl-any base:check-keep; do
  a=${arm%%:*}; w=${arm##*:}
  cd $M-wt/$w && python3 editor/roll.py $L --turn 27 --n $n --stop end --max-turns 14 --replayed --out $H/t1_$a.jsonl -- "${A[@]}" --tag t1_$a > $H/t1_$a.out 2>&1
  echo "$(date +%H:%M:%S) $a $(git rev-parse --short HEAD) $(tail -n 1 $H/t1_$a.out | cut -c1-100)"
done
