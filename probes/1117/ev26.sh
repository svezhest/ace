#!/bin/bash
# EV26: подача автора (v2) против EV6a на всём размеченном наборе — 16 оставшихся правок EV20 + 40 итоговых src oQ4e
# (без спорных и без уже снятых в EV25). Стенд — oQ4e нового рецепта (q8 KV, DRAFT=auto), тот же, что в EV25;
# ответы пишутся в те же runs/evw_1113/ev25_<var>_plain27.jsonl. Сначала сборка входов (без модели), потом вызовы
# парами v2 → ev6a на каждом теге, чтобы при обрыве сравнение оставалось парным.
cd /Users/user/Projects/nrhsi
T20="00_ev_s1 00_ev_s2 01_ev_s1 04_ev_s1 04_nl_s1 14_ev_s2 14_ev_s3 14_nl_s1 01_ev_s2 03_ev_s1 03_ev_s2 03_nl_s1 06_ev_s2 07_ev_s1 07_ev_s2 09_ev_s2"
TO4="00_bl_o4_s1 00_bl_o4_s2 00_cx_o4_s1 01_bl_o4_s1 01_bl_o4_s2 01_ck_o4_s1 01_ck_o4_s2 01_cx_o4_s1 03_bl_o4_s2 03_ck_o4_s2 03_cx_o4_s1
 04_bl_o4_s1 04_bl_o4_s2 04_ck_o4_s1 04_ck_o4_s2 04_cx_o4_s1 05_bl_o4_s1 05_bl_o4_s2 05_ck_o4_s1 05_ck_o4_s2
 06_bl_o4_s1 06_bl_o4_s2 06_ck_o4_s1 06_cx_o4_s1 07_bl_o4_s1 07_bl_o4_s2 07_ck_o4_s1 07_ck_o4_s2 07_cx_o4_s1
 09_bl_o4_s1 09_bl_o4_s2 09_ck_o4_s1 09_ck_o4_s2 14_bl_o4_s1 14_ck_o4_s1 14_cx_o4_s1 t4_bl_o4_s2 t4_ck_o4_s1 t4_ck_o4_s2 t4_cx_o4_s1"
for v in v2 ev6a; do for t in $T20 $TO4; do
  [ -s runs/evw_1113/ev25_in/$v/$t.txt ] || python3 probes/1116/ev25.py build $v $t || python3 probes/1116/ev25.py build $v $t
done; done
echo "$(date +%H:%M:%S) BUILD DONE"
[ "$1" = build ] && exit 0
for t in $T20 $TO4; do python3 probes/1116/ev25.py call v2 $t; python3 probes/1116/ev25.py call ev6a $t; done
echo "$(date +%H:%M:%S) EV26_DONE"
