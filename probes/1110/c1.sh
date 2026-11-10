S=/private/tmp/claude-501/-Users-user-Projects-itmo/0b27b398-da99-461f-b5a5-02754fadcd5d/scratchpad/fk
cd ~/Projects/nrhsi
j() { python3 -c "import json,sys;print(json.load(open('$S/c1.json'))[sys.argv[1]],end='')" $1; }
for pt in "g5_r2 16" "g5_r9 15"; do set -- ${=pt}; L=$S/h_g5/logs/$1.jsonl
  python3 editor/fork.py $L --turn $2 --n 10 --final --out $S/c1_$1_base.jsonl >/dev/null 2>$S/c1.err
  python3 editor/fork.py $L --turn $2 --n 10 --final --sub "$(j old)" "$(j list)" --out $S/c1_$1_list.jsonl >/dev/null 2>>$S/c1.err
  python3 editor/fork.py $L --turn $2 --n 10 --final --sub "$(j note)" "$(j rep)" --out $S/c1_$1_rep.jsonl >/dev/null 2>>$S/c1.err
done; date +%H:%M:%S; tail -3 $S/c1.err
python3 $S/cls.py $S/c1_g5_r2_*.jsonl $S/c1_g5_r9_*.jsonl
