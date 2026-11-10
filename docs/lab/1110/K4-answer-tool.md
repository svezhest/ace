# K4 — условие с инструментами `test` и `answer`, входы 08 и 00

[Указатель проб](../INDEX.md) · хронология: [10.11](../days/1110.md) · как устроено — [README](../README.md)

*Из записи «10.11, 17:27 — K3 прочитана; K4 постановка (вход 08 и второй вход 00)» (LAB-1110.md; заголовок и остальное — в [K3](K3-test-tool-v2.md)):*

<!-- LAB-1110.md:753–767 -->
- **K4 (постановка).** Прототип `fk/cond/k4.py`, кода в репозитории нет. Против K3:
  - инструмент `answer(condition, statement)` с проверкой, как `finish` у писателя: условие вычисляется на обоих
    прогонах; отказ — «true at N steps of run K, which passed: …» или «not true at any step of run F»;
  - в описании имён: «`earlier[-1]` is the step right before the current one, `earlier[-2]` the one before that»;
    в `IndexError` дописано, сколько шагов в `earlier` на этом шаге;
  - до 12 ходов, на последнем доступен только `answer`; бюджет рассуждения 2048 (вдвое дешевле; с инструментом
    проверять в уме не нужно);
  - вид, вход и номера прогонов — параметры: 08 (`alf_r1`, 40 / 28) и 00 (`alf_n4`, 6 / 1), по 10 сессий.
- **Проверка без модели.** 08: «равен шагу через один и отличен от соседа» — принято; «встречался раньше» — отказ
  (6 шагов run 28); буквальное `step.action == "examine dresser 1"` — **принято**: проверка общность не видит, её
  смотреть глазами. 00 труднее: «равен шагу через три» истинно и в run 1 (шаги 20–22, 29–30 — короткий цикл из трёх);
  разделяет «равен шагам через три и через шесть».
- **Мерка.** Принято ли (механически); глазами — структурное или буквальное, соответствует ли фраза условию.
- **Ожидание (до замера).** 08: принято 6 из 10, из них структурных 5. 00: принято 4 из 10, структурных 3.

## Итог (10.11, записан в 19:07 по `date`)

Запуск — `probes/1110/cond/k4.py`, по 10 сессий на вход, 4 потока, стенд thinking (бюджет 2048), до 12 ходов.
Сырьё: `runs/fk_1110/cond/k4_08.{out,jsonl}`, `k4_00.{out,jsonl}`.

| вход | принято | ожидание | фраза соответствует условию | общее условие (сдвиг относительно текущего шага) |
|---|---|---|---|---|
| 08 (run 40 / 28) | 7 из 10 | 6, структурных 5 | 7 | 7; буквальных 0 |
| 00 (run 6 / 1) | 6 из 10 | 4, структурных 3 | 4 | 3 |

- **08.** Приняты #0, #1, #3, #4, #5, #7, #9. У четырёх (#0, #1, #7, #9) «шаг равен шагу через один — и действие, и ответ»;
  у трёх (#3, #4, #5) только ответ, из них у #3 и #5 есть «и отличается от предыдущего». Провалы: #2 застрял на
  «встречался раньше», #6 восемь раз повторил одну проверку, #8 — восемь `IndexError` без `len(earlier) >= 2`.
- **00.** Приняты #0, #1, #2, #4, #7, #9.
  - #1, #7, #9 — «равен шагам через три и через шесть» (ответ; действие и ответ; действие). Это то условие, которое
    проверка без модели назвала разделяющим.
  - #0 и #4 — `earlier[3] == step`: сравнение с четвёртым шагом прогона, а не с шагом «три назад». Проверка приняла,
    фраза говорит «three steps earlier» — **фраза условию не соответствует**, условие привязано к месту в прогоне.
  - #2 — `any(earlier[i].observation == earlier[i+1].observation …)`: на текущий шаг не смотрит и после первого
    совпадения истинно до конца прогона. Фраза соответствует, условие слабое.
  - Не приняты: #3 дважды ответил `False`, у #5, #6, #8 ответ отклонён (условие истинно и в run 1).
- **IndexError.** 08: 19 вызовов из 82, в 8 сессиях. 00: 29 из 100. Подсказка в тексте ошибки («earlier has 0 steps at
  step 1») есть, но ошибка повторяется: это главный расход ходов.
- **Цена.** 08: 126–1132 с на принятое, сумма по 10 сессиям 7559 с (≈ 32 мин на 4 потоках). 00: 284–1231 с на принятое,
  сумма 9279 с (≈ 39 мин). Рассуждение ≈ 5300–6900 знаков на ход.

**Что это значит.** С инструментом проверки 9B находит условие над историей шагов в 13 сессиях из 20; буквальных
(названное действие или предмет) нет ни одного. Проверка на двух прогонах пропускает условие, привязанное к номеру
шага (2 из 13), — как и буквальное: общность она не видит.

**Не проверено.** Только два входа ALF, оба — про цикл. Ни одно принятое условие не вставлялось в `hooks.py` и не
шло через проверку писателя. Не пробовали: считать `IndexError` ложью на шаге; отвечать на повтор той же проверки;
третий прогон в проверке, чтобы отсечь привязку к номеру шага. Чтение «соответствует ли фраза» — один читатель.

## Код

<!-- LAB-1110.md:768–799 -->
**Код и запуск K4** (приписано 10.11). `probes/1110/cond/k4.py OUT N BUDGET MAXTURNS VIEW OBSFILE FAIL KEEP`. Что видит модель кроме наблюдения и двух списков шагов — цель и описания инструментов (строки 101–121 файла):

```python
---
The harness will be changed so that it notices this problem while a run is going. At each step its code has the current step and the earlier steps of the same run, and nothing else. The same code will run on other tasks, with other objects and actions, and should notice the same problem there.

Find the condition on the current step and the earlier steps that holds at the steps of run {FAIL} where the problem shows and does not hold at any step of run {KEEP}. `test` checks a condition on both runs. When a condition does this, hand it in with `answer`, together with one or two sentences that state it in words, exactly enough to be checked step by step; these sentences will be added to the observation."""
NAMES = ("Names in the expression: `step` — the current step, with `step.action` and `step.observation` (strings); "
         "`earlier` — the earlier steps of the same run as a tuple, oldest first: `earlier[-1]` is the step right "
         "before the current one, `earlier[-2]` the one before that.")
T_TEST = {"type": "function", "function": {
    "name": "test",
    "description": f"Evaluate a Python expression at every step of run {FAIL} and run {KEEP} and report the steps "
                   f"where it is true. {NAMES}",
    "parameters": {"type": "object", "properties": {"condition": {"type": "string", "description": "a Python expression"}},
                   "required": ["condition"]}}}
T_ANSWER = {"type": "function", "function": {
    "name": "answer",
    "description": "Hand in the condition and the sentences that state it in words. The condition is checked on both "
                   "runs as in `test`.",
    "parameters": {"type": "object", "properties": {
        "condition": {"type": "string", "description": "the Python expression, as in `test`"},
        "statement": {"type": "string", "description": "one or two sentences that state the condition in words"}},
        "required": ["condition", "statement"]}}}
```

```sh
cd $S/cond; N=runs/typed_1110
python3 k4.py k4_08.jsonl 10 2048 12 $N/alf_r1 $N/in/08_v_rr.txt 40 28 > k4_08.out
python3 k4.py k4_00.jsonl 10 2048 12 $N/alf_n4 $N/in/00_v_rr.txt 6 1 > k4_00.out
```
