# probes/ — код ручных проб

Одноразовые скрипты и входы проб, как они запускались. Лежали в scratchpad сессии, в репозиторий внесены 10.11, чтобы
запись журнала можно было прочитать вместе с кодом. Это записи, а не инструменты: пути внутри — scratchpad той сессии
(данные проб скопированы в `runs/mp_1109/` и `runs/fk_1110/`, вне git), аргументы писателя — на коде того часа.
Живые инструменты стенда — в `editor/` (`fork.py`, `roll.py`, `replay.py`, `rerun.py`, `val_edit.py`).

| каталог | журнал | что |
|---|---|---|
| `1109-mp/` | `docs/LAB-1109.md`, пробы [MP](../docs/lab/1109/MP-manual-additions.md), [MP2](../docs/lab/1109/MP2-check-own-condition.md), [MP3](../docs/lab/1109/MP3-thinking.md) | один вопрос модели без обвязки: `build*.py` собирает батарею, `run*.py` опрашивает, `ev.py` и `t3.py` меряют ответы офлайн. `battery2.json` (840 КБ, собирается `build2.py`) — только в `runs/mp_1109/` |
| `1110/` | `docs/LAB-1110.md`, G, H, T, C, F ([указатель, 10.11](../docs/lab/INDEX.md); код и запуск G1–G5 — [G1–G5 (код)](../docs/lab/1110/G1-G5-code.md)) | `args08.sh` — аргументы писателя на входе 08 (до a13b543, с флагами базы), `args08_now.sh` — те же на нынешнем коде; `08_cond.txt` — вход 08 с условием (G5, G9); `c1.sh`, `c1.json` — проба C1; `h1_locals.txt`, `h2_nopf*.txt` — подменённые ответы инструмента в H1/H2; `cls.py` — сводка ответов развилки; `tk_test.py` — проверка тикета на готовой копии |
| `1110/cond/` | `docs/LAB-1110.md`, [K1](../docs/lab/1110/K1-condition-one-call.md), [K1c](../docs/lab/1110/K1c-with-run28.md), [K2](../docs/lab/1110/K2-test-tool.md), [K3](../docs/lab/1110/K3-test-tool-v2.md), [K4](../docs/lab/1110/K4-answer-tool.md) | 9B формулирует условие: `cond.py` + `pA/pB/pC.txt` (один вызов), `k2.py`, `k3.py`, `k4.py` (инструменты `test` и `answer`) |
| `1110/gold/` | `docs/LAB-1110.md`, чистка кода ([10.11](../docs/lab/days/1110.md)) | сверка кода до и после чистки: `gold.sh` (проигрыши `editor/replay.py`), `tk_all.py` (проверка тикета на готовых копиях) |
