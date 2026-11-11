#!/bin/bash
# start.sh NN TAG [--dry] — сессия писателя на базе (вход NN, вид и тикет базы), за модель отвечает агент через hand.py
view() { case $1 in 00) echo alf_n4;; 01|03) echo app_r1;; 04|05) echo app_r4;; 06|08) echo alf_r1;; 07) echo alf_r4chk;; 09) echo app_n2;; esac; }
cd /Users/user/Projects/nrhsi; v=$(view $1); b=${v%%_*}
exec python3 probes/1111/hand/run_hand.py -- --bench $b --view runs/typed_1111/$v --input-text runs/typed_1111/in/$1_v_rr.txt \
  --ticket docs/tickets_1106k/$1.json --seed 1 --stand default --lint editor/lint --home runs/hand_1111 --tag $2 $3
