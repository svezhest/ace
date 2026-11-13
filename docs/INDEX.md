# Индекс документации NRHSI

Логическая карта: части метода и линии работы → подтемы → документы и пробы журнала. Каждый документ стоит под главной
темой; из других тем на него ведёт ссылка. Строка документа: ссылка — дата — о чём — чем кончилось.

Хронологический вид уже есть: дневник диплома 3.09–6.11 — [diary.html](../../itmo/cs-masters/thesis/diary.html)
(вне репозитория; до 29.10 — [предыстория](index/prehistory.md)), пробы по дням — [lab/INDEX](lab/INDEX.md), записи дня — [lab/days/](lab/days/1113.md),
дневники 29.10–6.11 — [ход работы](index/meta.md#дневники-и-ночные-сводки).

**Открытые задачи — отдельно: [TASKS.md](TASKS.md).**

## Дерево

1. **[Метод целиком](index/method.md)** — цикл NRHSI ([README](../README.md)), дерево и выбор узла, замер узла на val
   (§1 Val, P0, VAL-V), слияние узлов (P4).
2. **[Стенд и бенчмарки](index/bench.md)** — ALFWorld и AppWorld как апстрим (журналы фаз, UPSTREAM), стартовый
   харнесс и README для модели, представление трасс (TRACE-VIEWS), модель и профиль стенда.
3. **[Исследователь (ревьювер)](index/reviewer.md)** — калибровка 28–31.10 (researcher/JOURNAL, AUDIT, IDEAS,
   лестница дневника, P5); эталон и разметка находок (eval/); проверяльщик R2 (verifier/JOURNAL); отчёты как входы писателя.
4. **[Писатель](index/writer.md)** — главная линия с 3.11:
   1. ранний редактор 29–31.10 (editor/JOURNAL);
   2. мерка и потолок формата (P7, P7b);
   3. входы писателя: наблюдения и тикеты (`tickets_*`, `base/`);
   4. добавки 3.11 (P1–P3, P6);
   5. варианты W и блоки абляции 4–6.11;
   6. тонкий писатель (THIN-1104 ↔ lab THIN);
   7. пул правок и отбор (GC);
   8. ручной режим: b1–b4, MP–MP3;
   9. проверка по тикету TK* и keep (REPORT-1106);
   10. чистая база (CL, PL, NT, повтор);
   11. чистка кода 10.11 (CODE-MAP, REMOVED);
   12. ручная отладка по тикету 10.11 (TICKET-1110-*, ST*, развилки G/T/F/K/H);
   13. лестница моделей 11–12.11 (DeepSeek, 27B T/NT, разбор с автором).
   Сводные: каталог ошибок 9B (CAT), AGREE-1105, READ-writer-1103.
5. **[Судья и оценщик правки](index/judge.md)** — судья v1 (в THIN-1104) → судья v2 (JUDGE-1105 ↔ lab JV2) → судья в
   пуле GC, jgp → оценщик правки EV (план, EV0–EV12).
6. **[Приборы стенда писателя](index/instruments.md)** — перепрогон rerun (ST1 ядро, RL, RC), развилки fork/roll (ST2,
   детерминизм), smoke, песочница и Python.
7. **[Ход работы и способ работы](index/meta.md)** — устройство лабораторного журнала (README, INDEX, OLD-LINES,
   заглушки LAB-*), хронология по дням, дневники и ночные сводки, выборы автора и промпт оркестратора, PROGRESS, BACKLOG.
8. **[Предыстория до NRHSI](index/prehistory.md)** (3.09–28.10, по [дневнику диплома](../../itmo/cs-masters/thesis/diary.html))
   — тема и обзоры; репликация ACE/SCOPE/DC (ни один метод не отделился от baseline); стенд `~/Projects/ace` и
   верность апстриму (запись и побайтный replay); поворот 10.10 и AppWorld (баг оценки, прокси v1–v9, «9B пишет
   харнесс» свёрнута 20.10); train, Δlog p, дерево v1–v3; пробы ревьювера, загрязнения, новизна, исследователь fsr.

## Расхождения дневника диплома и docs

Приведены оба числа с источниками; какое верное — не решаю.
- **ALF n4 на val:** 65/111 (n0 65/107, на 107 общих 61) — [§1 Val](lab/1103/VAL1-tree-node-val.md) и
  [дневник 3.11](../../itmo/cs-masters/thesis/diary.html#d2026-11-03); 66/112 — [дневник 5.11](../../itmo/cs-masters/thesis/diary.html#d2026-11-05)
  и [DIARY-1105](DIARY-1105.md) («по `runs/val_1102/*/meta.jsonl` итог такой»); 60/106 против n0 62/102 —
  [lab/days/1105](lab/days/1105.md) (DIARY-1105 называет это промежуточным счётом). → [метод](index/method.md#замер-узла-на-val).
- **K исследователя:** дневник 29.10 — ALF K=5, App «при лимите 40 предложено K=3»; researcher/JOURNAL §6.4 — общий
  K=3; README и проба A7 — K=5. → [ревьювер](index/reviewer.md#калибровка-исследователя-283110).
- **Абляции train 22.10 (демо 49, правила 34):** [PROGRESS-0903-1106](PROGRESS-0903-1106.md) даёт их как замер;
  дневник («Неясности», кусок 7) — «выведены из „+34/+19 к базе 15“», итоговых строк в репликах нет. → [предыстория](index/prehistory.md).

## Связи «журнал агента ↔ запись в lab»

| документ в `docs/` | запись в `docs/lab/` | отношение |
|---|---|---|
| [THIN-1104](THIN-1104.md) | [1104/THIN-thin-writer](lab/1104/THIN-thin-writer.md) | журнал агента ветки `feature/thin-writer` ↔ постановка и итог пробы |
| [JUDGE-1105](JUDGE-1105.md) | [1105/JV2-reading-judge](lab/1105/JV2-reading-judge.md) | журнал судьи v2 ↔ постановка и итог пробы |
| [AGREE-1105](AGREE-1105.md) | [1105/AGREE-agreement](lab/1105/AGREE-agreement.md) | классификация агента ↔ постановка и итог разбора |
| [REPORT-1106](REPORT-1106.md) | [IO…BR](lab/1105/IO-AQ-NV2-TP-BR.md), [SW1/SNV](lab/1105/SW1-SNV-symptom-only.md), [b1](lab/1106/b1-ask-manual.md)–[b4](lab/1106/b4-choice-swapped.md), [TK*](lab/1106/TK-TKS-ticket.md) | сводный отчёт ночи 6.11 по этим пробам |
| [READ-writer-1103](READ-writer-1103.md) | [P6](lab/1103/P6-smoke-calls.md), [P4](lab/1103/P4-merge.md), [P7](lab/1103/P7-ideal-input.md) | ручной разбор, на который ссылаются пробы |
| [TICKET-1110-writer](TICKET-1110-writer.md), [-status](TICKET-1110-status.md) | ST1–ST7 в [1110/](lab/1110/ST3-input-map.md), [ST4](lab/1111/ST4-reference-agent.md) | тикет и его шаги |
| [CODE-MAP-1110](CODE-MAP-1110.md), [REMOVED-1110](REMOVED-1110.md) | [10.11](lab/days/1110.md), [ST1 ядро](lab/1110/ST1-rerun-core.md) | карта и опись чистки кода |
| [LAB-1103](LAB-1103.md), [LAB-1109](LAB-1109.md), [LAB-1110](LAB-1110.md) | весь [lab/](lab/README.md) | старые сплошные журналы разложены по пробам |

## Что не индексируется

- `runs/` — данные прогонов.
- `researcher/views/*/README.md`, `editor/work/*/README.md`, `alfworld/view*/README.md`, `appworld/view*/README.md`,
  `*/views_e3/` — README для модели, скопированные в каждый вид или копию сессии (оригинал — `start/*.README.md`).
- `researcher/out/s*.md` — выходы сессий; `alfworld/ref/` — чужие репозитории; `.pytest_cache/`.
- `start/<бенч>/*.md` — промпты харнесса; `stands/*.json` — профили; `probes/` (кроме README) — код и входы проб.
