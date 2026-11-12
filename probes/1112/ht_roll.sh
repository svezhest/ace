#!/bin/bash
# ht_roll.sh [N=5] [SEED=1] — проба HT: та же развилка, что в PF (ход 25 сессии runs/n27_1111/logs/t1_plain27t_s1.jsonl, сразу после
# ответа проверки «Failed: this edit changes run 8…»), но ответ даёт 27B с рассуждением (профиль think27t, T=0,6):
# история — от сессии без рассуждения, думает модель только на ходах после развилки. Код feature/check-keep-passed,
# история проиграна своим харнессом (--replayed). База — плечо base пробы PF (тот же код, без рассуждения).
M=/Users/user/Projects/nrhsi; T=$M/runs/typed_1111; n=${1:-5}; sd=${2:-1}; H=$M/runs/ht_1112; mkdir -p $H
A=(--bench app --view $T/app_r1 --input-text $T/in/t1.txt --ticket $M/docs/tickets_1111/t1.json --home $H --seed $sd --stand think27t --lint $M/editor/lint)
L=$M/runs/n27_1111/logs/t1_plain27t_s1.jsonl
cd $M-wt/check-keep && python3 editor/roll.py $L --turn 25 --n $n --stop checked --max-turns 4 --replayed --out $H/t1_ht_s$sd.jsonl -- "${A[@]}" --tag t1_ht_s$sd > $H/t1_ht_s$sd.out 2>&1
echo "$(date +%H:%M:%S) ht $(git rev-parse --short HEAD) $(tail -n 1 $H/t1_ht_s$sd.out | cut -c1-100)"
