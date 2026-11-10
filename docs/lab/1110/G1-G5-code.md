# G1–G5 (код) — код и запуск проб G1–G5

[Указатель проб](../INDEX.md) · хронология: [10.11](../days/1110.md) · как устроено — [README](../README.md)

## Код

<!-- LAB-1110.md:241–263 -->
**Код и запуск** (приписано 10.11 при чистке кода). `$S` — каталог данных проб: scratchpad сессии, копия в `runs/fk_1110/` (вне git). Скрипты и входы — в `probes/1110/`. `ARGS08` — `probes/1110/args08.sh`: аргументы писателя для входа 08 на коде того часа, с флагами базы; на коде после a13b543 — `args08_now.sh`.

Приборы — `editor/fork.py` и `editor/roll.py` (7f21310, 3c1cdb8). Запуски проб этой записи:

```sh
cp runs/wvar_1104/08_TY_s1/logs/wv_08_TY_s1.jsonl $S/08a.jsonl      # сессия-источник развилок; source $S/args08.sh
# G1, один ход на развилке (01:05) и прокат с хода 1 до первой правки (01:10)
python3 editor/fork.py $S/08a.jsonl --turn 14 --n 10 --chars 150 --out $S/g1_base.jsonl
python3 editor/fork.py $S/08a.jsonl --turn 14 --n 10 --chars 150 --out $S/g1_goal.jsonl --sub "Your goal: change src/ so that the agent fails fewer tasks. Each observation that points to a weakness of the harness is a candidate for a change." "Your goal: make the change to src/ that the observation calls for, so that the harness handles the situation it describes." --sub "Change src/ so that the agent fails fewer tasks." "Change src/ so that the harness handles what the observation describes."
python3 editor/roll.py $S/08a.jsonl --turn 1 --n 10 --max-turns 30 --out $S/r1_base.jsonl -- --home $S/h_base --tag b "${ARGS08[@]}"
python3 editor/roll.py $S/08a.jsonl --turn 1 --n 10 --max-turns 30 --out $S/r1_goal.jsonl --sub "Your goal: change src/ so that the agent fails fewer tasks. Each observation that points to a weakness of the harness is a candidate for a change." "Your goal: make the change to src/ that the observation calls for, so that the harness handles the situation it describes." --sub "Change src/ so that the agent fails fewer tasks." "Change src/ so that the harness handles what the observation describes." -- --home $S/h_goal --tag g "${ARGS08[@]}"
# G2, формулировка Failed (01:52): две сессии до ответа проверки, затем развилка хода после него
python3 editor/roll.py $S/08a.jsonl --turn 14 --n 2 --max-turns 8 --stop checked --out $S/t.jsonl -- --home $S/h_t --tag t "${ARGS08[@]}"
OLD="Failed: run 40 goes exactly as in the log, to the end: this edit changes nothing in it"; NEW="Failed: this edit has no effect in run 40, the run the observation is about"
for p in "r0 17" "r1 20"; do set -- ${=p}; python3 editor/fork.py $S/h_t/logs/t_$1.jsonl --turn $2 --n 10 --chars 420 > $S/g2_$1_base.txt
  python3 editor/fork.py $S/h_t/logs/t_$1.jsonl --turn $2 --n 10 --chars 420 --sub "$OLD" "$NEW" > $S/g2_$1_new.txt; done
# G3, сессии целиком (01:56); G4, хвост 10 (02:22); G5, условие во входе (02:30)
python3 editor/roll.py $S/08a.jsonl --turn 1 --n 10 --max-turns 45 --stop end --out $S/g3.jsonl -- --home $S/h_g3 --tag g3 "${ARGS08[@]}"
python3 editor/roll.py $S/08a.jsonl --turn 1 --n 10 --max-turns 55 --stop end --final-turns 10 --out $S/g4.jsonl -- --home $S/h_g4 --tag g4 "${ARGS08[@]}"
A=("${ARGS08[@]}"); for i in {1..${#A[@]}}; do [ "${A[$i]}" = "--input-text" ] && A[$((i+1))]=$S/08_cond.txt; done   # вход: probes/1110/08_cond.txt
python3 editor/roll.py $S/08a.jsonl --turn 1 --n 10 --max-turns 45 --stop end --out $S/g5.jsonl -- --home $S/h_g5 --tag g5 "${A[@]}"
```
