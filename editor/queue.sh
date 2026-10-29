#!/bin/bash
# queue.sh "bench:input" ...  — по входу: плечи obs и fix одновременно (2 сессии модели), затем следующий вход.
cd "$(dirname "$0")"
for x in "$@"; do
  b=${x%%:*}; i=${x##*:}
  python3 editor.py --bench $b --input $i --arm obs --seed 1 --tag b1_${b}_${i}_obs > logs/b1_${b}_${i}_obs.out 2>&1 &
  p1=$!
  python3 editor.py --bench $b --input $i --arm fix --seed 1 --tag b1_${b}_${i}_fix > logs/b1_${b}_${i}_fix.out 2>&1 &
  p2=$!
  echo "$(date +%T) $x pids $p1 $p2"
  wait $p1 $p2
  echo "$(date +%T) $x done"
done
