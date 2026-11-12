#!/bin/bash
# cf_roll.sh [N=10] — проба CF: развилка на ходу первой правки сессии runs/n27_1111/logs/t1_plain27t_s1.jsonl (ход 24),
# по N ответов на плечо, до ответа проверки на первую правку (--stop checked). base — история как записана;
# blk — в первое сообщение после наблюдения вставлен раздел «Passed runs» из docs/tickets_1112/t1c.txt (--sub).
# Код develop. Результаты — runs/cf_1112.
M=/Users/user/Projects/nrhsi; T=$M/runs/typed_1111; n=${1:-10}; H=$M/runs/cf_1112; mkdir -p $H
A=(--bench app --view $T/app_r1 --input-text $T/in/t1.txt --ticket $M/docs/tickets_1111/t1.json --home $H --seed 1 --stand plain27t --lint $M/editor/lint)
L=$M/runs/n27_1111/logs/t1_plain27t_s1.jsonl
OLD='- src/harness.py:95 `code == steps[-1].code` compares only with the previous step'
NEW="$OLD"$'\n\n'"$(sed -n '/^## Passed runs/,$p' $M/docs/tickets_1112/t1c.txt)"
cd $M
python3 editor/roll.py $L --turn 24 --n $n --stop checked --max-turns 4 --out $H/t1_base.jsonl -- "${A[@]}" --tag t1_base > $H/t1_base.out 2>&1
echo "$(date +%H:%M:%S) base $(tail -n 1 $H/t1_base.out | cut -c1-100)"
python3 editor/roll.py $L --turn 24 --n $n --stop checked --max-turns 4 --sub "$OLD" "$NEW" --out $H/t1_blk.jsonl -- "${A[@]}" --tag t1_blk > $H/t1_blk.out 2>&1
echo "$(date +%H:%M:%S) blk $(tail -n 1 $H/t1_blk.out | cut -c1-100)"
