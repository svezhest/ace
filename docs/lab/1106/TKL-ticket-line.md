# TKL — факт покрытия одной фразой в строке Failed (`--ticket-line`)

[Указатель проб](../INDEX.md) · хронология: [6.11](../days/1106.md) · как устроено — [README](../README.md)

<!-- LAB-1103.md:2334–2352 -->
### TKL: факт покрытия одной фразой в строке Failed (6.11, 07:10)
- Повод: покрытие таблицей не читается (0 ссылок в 10 сессиях), а строку Failed писатель замечает примерно в половине случаев.
- `--ticket-line` (только gate, `editor/rerun.py` не тронут). К строке «Failed: run N goes exactly as in the log…» дописывается «; in run N your `<строка>` at src/F:L ran K times and was never true» — до двух таких фактов, чаще выполнявшиеся первыми.
  - Условие: `if`/`elif`/`while` (в том числе многострочное), тело которого не выполнялось.
  - Или `return <выражение>`, вернувшее всегда одно значение (False/None/True). Литералы вроде `return False` не в счёт.
  - Иначе — первая изменённая строка, которая не выполнялась после выполнявшейся: «… never ran».
  - Иначе — «none of the lines you changed ran in it».
- Проверено на готовых сессиях (`scratchpad b1/tc_test.py`):
  - 00_TK — оба `if stalled/in_cycle` 50 раз и ни разу не истинны;
  - 00_TKC — `return len(set(...)) == 1` всегда False;
  - 08_IO — `return {` never ran;
  - 08_TKC — `if len(observations) >= 2 and …` 50 раз, ни разу;
  - 06_TK — `action = ctx.get("action")` never ran;
  - 01_TKC — «none of the lines you changed ran in it»;
  - 03_TK, 01_TK — факта нет, строка как раньше.
- `--dry` с флагом совпадает с TKS байт в байт.
- Сессии `wv_NN_TKL` = TKS + `--ticket-line`, seed 1, в очереди после TKF.
- Мерка: ссылается ли писатель на названную строку; правит ли её; V/P/B/x.

*Из записи «TKR итог, TKL/TKF 00–03 (6.11, 07:25)» (LAB-1103.md; заголовок и остальное — в [TKC, TKR](TKC-TKR-cover.md)):*

<!-- LAB-1103.md:2370–2385 -->
**Процесс — первые ссылки на факт покрытия:**
- **00_TKL — первая за весь день сессия, где писатель взял факт из проверки и пошёл по нему.** Строка: «your `return len(set(observations[-3:])) == 1` at :126 ran 47 times and returned False every time».
  - Его реакция: «The change works but doesn't affect run 6. Let me examine why… The rerun output said line 126 ran and returned False. Let me check».
  - Затем `rerun.py 6 --at 46` → «these are **3 distinct observations**, not identical!» → правильный вывод о цикле из трёх разных наблюдений → проверка на удачных 19 и 30, где он нашёл, что наивный тест сработает и там.
  - Итоговая правка (`_period`) тикет всё же не задела, x. Но разбор шёл от факта, а не от догадки.
  - Та же сессия без строки (00_TKS) и с таблицей (00_TKC) этого не сделала: TKS разбирал сам, TKC прочёл наоборот.
- **01_TKL — «не верю прибору» вопреки факту.** Строка: «your `if obs == …[-1] or obs in …` at :164 ran 49 times and was never true».
  - Его реакция: «The rerun test confirms my analysis is correct: the harness now *would* catch the loop, but the log stopped recording at step 50, so the replay can't show it».
  - Это ложь о приборе: условие выполнилось 49 раз в записанных шагах.
  - Здесь факт был прочитан и отброшен.
- Итог 2 из 2: строка в Failed читается, в отличие от таблицы (0 из 10). Принята в 1 из 2.

**Что дальше.**
- Ждать TKL 04–09.
- Если писатель отбрасывает факт, ему нечем себя опровергнуть кроме нашего текста. Следующая ступень — показать в той же строке значения операндов на шаге, где он ждёт срабатывания: что сравнивалось с чем. Так факт «never true» становится проверяемым глазами. 00_TKL сделал это сам через `--at`; 01_TKL — нет.

<!-- LAB-1103.md:2411–2417 -->
### TKL и TKF итог (6.11, 08:05)
| | 00 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 |
|---|---|---|---|---|---|---|---|---|---|---|
| TKL | x | x | V | x | x (= TKC) | P | x (= TKS) | x (тавтология `empty_note`) | x | P |
| TKF | x | x | V | x | x (docstring) | P | x | B | x | B |

- **TKL 09** — хук `on_error`: при NameError на имени из примера (`num_playlists` и др.) объясняет, что пример — о другой задаче, плюс строка в промпте. Задеты 2 удачных. Ставлю P по промпту; хук привязан к именам примера из промпта харнесса (не бенча), узкий, но хрупкий.

*[…] строки этой записи между предыдущим куском и этим — в: [TKF](TKF-ticket-first.md)*

<!-- LAB-1103.md:2421–2422 -->
- V/P/B/x: TKL 1/2/0/7, TKF 1/1/2/6. Против TKS s1 2/2/0/6, TKC 1/2/0/7, TKR 1/1/0/8.
- **По вердиктам ни одна ступень не отличается от TKS.**

*[…] строки этой записи между предыдущим куском и этим — в: [TKF](TKF-ticket-first.md)*

<!-- LAB-1103.md:2425–2432 -->
**Процесс TKL: факт в строке Failed показан в 3 сессиях (00, 01, 08):**
- **Принят и разобран — 2:**
  - 00 — «rerun output said line 126 … returned False. Let me check» → `--at`;
  - 08 — «The rerun output confirms… the condition was never true… Let me investigate why the observations aren't matching» → нашёл, что соседние наблюдения цикла разные, перенёс проверку в `on_before_action`.
- **Отброшен — 1:** 01 («the log stopped recording at step 50, so the replay can't show it»).
- Для сравнения: в TKC таблицу не прочитал ни один из 10.
- **Но разбор не дошёл до живой правки ни в 00, ни в 08.** Обе сессии упёрлись в лимит bash.

## Связанные записи

- [6.11](../days/1106.md): «TKR итог, TKL/TKF 00–03»: TKL 00–03 и совпадение итоговых правок
- [6.11](../days/1106.md): «Мерка: пары по месту расхождения»: факт в строке (TKL/TKS)
