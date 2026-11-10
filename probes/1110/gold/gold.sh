#!/bin/bash
# gold.sh old|new NAME — проигрыши базы писателя без модели в $G/NAME (сначала в $G/cur: пути одинаковы у обоих)
MODE=$1; NAME=$2
N=/Users/user/Projects/nrhsi; R=$N/runs; G=$(cd "$(dirname "$0")" && pwd); FK=$(dirname $G)
rm -rf $G/cur $G/$NAME; mkdir -p $G/cur
if [ $MODE = old ]; then BASE="--arm obs --rerun --auto-check --clean"; TK="--ticket-show --ticket-line --ticket-values --ticket-why"; else BASE=""; TK=""; fi
view() { case $1 in 00) echo alf_n4;; 01|02|03) echo app_r1;; 04|05) echo app_r4;; 06|08) echo alf_r1;; 07) echo alf_r4chk;; 09) echo app_n2;; esac; }
args() { # args IN [noticket]
  v=$(view $1); b=${v%%_*}
  [ $b = alf ] && { i=n4_2; L=$R/tree_alf_1101/n4.research/2/logs; } || { i=n0_2; L=$R/tree_app_1101/n0.research/2/logs; }
  echo -n "--bench $b --view $R/typed_1110/$v --seed 1 --stand default --lint $N/editor/lint $BASE"
  { [ $MODE = old ] || [ "$2" = noticket ]; } && echo -n " --rlogs $L --input $i"
  [ "$2" = noticket ] || echo -n " --input-text $R/typed_1110/in/$1_v_rr.txt --ticket $N/docs/tickets_1106k/$1.json $TK"
}
: > $G/cur/jobs
for i in 00 01 02 03 04 05 06 07 08 09; do for s in 1 2; do
  echo "$i-PL$s|$R/wvar_1104/${i}_PL_s$s/logs/wv_${i}_PL_s$s.jsonl|$(args $i)" >> $G/cur/jobs; done; done
for k in 0 1 2 3 4 5 6 7 8 9; do for g in g8 g9; do
  echo "08-$g-$k|$FK/h_$g/logs/${g}_r$k.jsonl|$(args 08)" >> $G/cur/jobs; done; done
echo "00-nt|$R/wvar_1104/00_PL_s1/logs/wv_00_PL_s1.jsonl|$(args 00 noticket)" >> $G/cur/jobs
echo "01-nt|$R/wvar_1104/01_PL_s1/logs/wv_01_PL_s1.jsonl|$(args 01 noticket)" >> $G/cur/jobs
for i in 00 01 02 03 04 05 06 07 08 09; do (cd $N && python3 -m nrhsi.editor $(args $i) --home $G/cur/dry --tag d --dry > $G/cur/dry_$i.txt 2>&1); done
(cd $N && python3 -m nrhsi.editor $(args 00 noticket) --home $G/cur/dry --tag d --dry > $G/cur/dry_00nt.txt 2>&1)
python3 $G/jobs.py $G
mv $G/cur $G/$NAME; echo done $(ls $G/$NAME | wc -l)
