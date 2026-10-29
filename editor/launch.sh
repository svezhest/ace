#!/bin/bash
# launch.sh BENCH INPUT ARM SEED TAG  — одна сессия редактора (плечо fix — с шагом вариантов), фоном; pid в logs/<tag>.pid
cd "$(dirname "$0")"
nohup python3 editor.py --bench "$1" --input "$2" --arm "$3" --seed "$4" --tag "$5" > "logs/$5.out" 2>&1 &
echo $! > "logs/$5.pid"; echo "$5 pid $!"
