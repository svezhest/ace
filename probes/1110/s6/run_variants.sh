#!/bin/bash
# Шаг 6 тикета 10.11: замер вариантов A, B, C. bash probes/1110/s6/run_variants.sh SCRATCH_HOME
# Первый ход по 20 раз на двух стендах (editor/fork.py), затем первые три хода (probes/1110/s6/roll3.py), по два проката разом.
cd "$(dirname "$0")/../../.." || exit 1
D=runs/fk_1110/s6; H=$1
Q='Before you start, answer in plain text, three short points: (1) what are you asked to do here; (2) how will you know it is done; (3) what will you do first. Reply with text only; the tools come after this answer.'
date '+fork start %H:%M:%S'
for v in A B C; do for nn in 05 06 08 09; do
  python3 editor/fork.py $D/$v/$nn.jsonl --turn 1 --n 20 --stand thinking --out $D/$v/$nn.think.jsonl > $D/$v/$nn.think.txt 2>&1 &
  python3 editor/fork.py $D/$v/$nn.jsonl --turn 1 --n 20 --stand default --note "$Q" --out $D/$v/$nn.ask.jsonl > $D/$v/$nn.ask.txt 2>&1 &
done; wait; done
date '+roll start %H:%M:%S'
for nn in 05 06 08 09; do
  python3 probes/1110/s6/roll3.py 0 $nn $H > $D/0.$nn.roll.log 2>&1 &
  python3 probes/1110/s6/roll3.py A $nn $H > $D/A.$nn.roll.log 2>&1 &
  wait
  python3 probes/1110/s6/roll3.py B $nn $H > $D/B.$nn.roll.log 2>&1 &
  python3 probes/1110/s6/roll3.py C $nn $H > $D/C.$nn.roll.log 2>&1 &
  wait
done
date '+end %H:%M:%S'
wc -l $D/[ABC]/*.think.jsonl $D/[ABC]/*.ask.jsonl $D/[0ABC]/*.roll.jsonl | tail -45
grep -l "error\|Traceback" $D/[ABC]/*.txt $D/*.roll.log
exit 0
