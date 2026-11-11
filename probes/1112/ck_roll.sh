#!/bin/bash
# ck_roll.sh ВХОД ХОД N — проба CK: докаты записанной сессии 27B NT (runs/n27_1111/logs/ВХОД_plain27t_s1.jsonl) с хода ХОД
# до конца, по N на плечо: ck — код ветки feature/check-keep-passed, история проиграна её харнессом (--replayed);
# base — код develop, история записанная. Результаты — runs/ck_1112.
M=/Users/user/Projects/nrhsi; T=$M/runs/typed_1111; t=$1; turn=$2; n=${3:-3}
A=(--bench app --view $T/app_r1 --input-text $T/in/$t.txt --ticket $M/docs/tickets_1111/$t.json --home $M/runs/ck_1112 --seed 1 --stand plain27t --lint $M/editor/lint)
L=$M/runs/n27_1111/logs/${t}_plain27t_s1.jsonl; mkdir -p $M/runs/ck_1112
cd $M-wt/check-keep && python3 editor/roll.py $L --turn $turn --n $n --stop end --max-turns 14 --replayed --out $M/runs/ck_1112/${t}_ck.jsonl -- "${A[@]}" --tag ${t}_ck > $M/runs/ck_1112/${t}_ck.out 2>&1
echo "$(date +%H:%M:%S) ck $(tail -n 1 $M/runs/ck_1112/${t}_ck.out | cut -c1-120)"
cd $M && python3 editor/roll.py $L --turn $turn --n $n --stop end --max-turns 14 --out $M/runs/ck_1112/${t}_base.jsonl -- "${A[@]}" --tag ${t}_base > $M/runs/ck_1112/${t}_base.out 2>&1
echo "$(date +%H:%M:%S) base $(tail -n 1 $M/runs/ck_1112/${t}_base.out | cut -c1-120)"
