#!/bin/bash
# EV26, урезано по слову автора («чем меньше токенов для сравнения тем лучше»): v2 на 9 F + 18 Ok (seed 1) итоговых src oQ4e;
# ev6a — только на 9 F (на Ok берётся вердикт оценщика из сессии писателя: в EV25 новый стенд повторил его 9 из 9).
cd /Users/user/Projects/nrhsi
F="00_bl_o4_s1 00_bl_o4_s2 01_bl_o4_s1 01_bl_o4_s2 01_ck_o4_s1 09_ck_o4_s2 14_bl_o4_s1 14_ck_o4_s1 14_cx_o4_s1"
OK="00_cx_o4_s1 01_cx_o4_s1 03_cx_o4_s1 04_bl_o4_s1 04_ck_o4_s1 04_cx_o4_s1 05_bl_o4_s1 05_ck_o4_s1 06_bl_o4_s1 06_ck_o4_s1 06_cx_o4_s1 07_bl_o4_s1 07_ck_o4_s1 07_cx_o4_s1 09_bl_o4_s1 09_ck_o4_s1 t4_ck_o4_s1 t4_cx_o4_s1"
for t in $F; do
  [ -s runs/evw_1113/ev25_in/ev6a/$t.txt ] || python3 probes/1116/ev25.py build ev6a $t
  python3 probes/1116/ev25.py call v2 $t; python3 probes/1116/ev25.py call ev6a $t
done
for t in $OK; do python3 probes/1116/ev25.py call v2 $t; done
echo "$(date +%H:%M:%S) EV26_DONE"
