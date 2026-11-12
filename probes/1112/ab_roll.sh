#!/bin/bash
# ab_roll.sh [N=3] — проба AB: докаты сессии runs/ck_1112/logs/t1_ck_r0.jsonl с хода 27 кодом ветки feature/asm-1112
# (feature/failed-line-any + feature/bash-unnamed: лимит bash 60, писателю не назван). В точке развилки израсходовано
# 24 вызова bash: в базе (плечо fa пробы FA, лимит 25) остаётся 1, здесь — 36. История проиграна своим харнессом
# (--replayed). Результаты — runs/ab_1112.
M=/Users/user/Projects/nrhsi; T=$M/runs/typed_1111; n=${1:-3}; H=$M/runs/ab_1112; mkdir -p $H
A=(--bench app --view $T/app_r1 --input-text $T/in/t1.txt --ticket $M/docs/tickets_1111/t1.json --home $H --seed 1 --stand plain27t --lint $M/editor/lint)
L=$M/runs/ck_1112/logs/t1_ck_r0.jsonl
cd $M-wt/asm && python3 editor/roll.py $L --turn 27 --n $n --stop end --max-turns 30 --replayed --out $H/t1_ab.jsonl -- "${A[@]}" --tag t1_ab > $H/t1_ab.out 2>&1
echo "$(date +%H:%M:%S) ab $(git rev-parse --short HEAD) $(tail -n 1 $H/t1_ab.out | cut -c1-100)"
