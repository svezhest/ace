# Предыстория до NRHSI: тема, репликация ACE, AppWorld, дерево, пробы ревьювера (3.09–28.10)

[Карта](MAP.md) · задачи — [TASKS](TASKS.md) · дневник диплома — [diary.html](../../itmo/cs-masters/thesis/diary.html)

Всё, что было до репозитория NRHSI (29.10). Главный источник — дневник диплома
`~/Projects/itmo/cs-masters/thesis/diary.html` (карточки дней с якорем `#dГГГГ-ММ-ДД`, в каждой «коротко» и
«подробно: замеры, решения, источники»). Разборы, на которые он ссылается, лежат рядом, в `cs-masters/thesis/`.
Дни по шкале уровней — [PROGRESS-0903-1106](PROGRESS-0903-1106.md) (он собран в том числе по этому дневнику).
Строка: дата (ссылка на карточку дня) — о чём — чем кончилось; «(дневник, ДД.ММ)» — откуда факт.

## Карта дневника

- [Карта: сентябрь, октябрь](../../itmo/cs-masters/thesis/diary.html) — сводка двух месяцев по линиям (диплом,
  BlueSec, llm, учёба) в начале файла.
- [Сентябрь](../../itmo/cs-masters/thesis/diary.html#m9), [октябрь](../../itmo/cs-masters/thesis/diary.html#m10),
  [ноябрь](../../itmo/cs-masters/thesis/diary.html#m11) — карточки дней. Ноябрьские (1–6.11) и октябрьские 29–31.10 —
  тот же текст, что [DIARY-1029…1106](MAP.md#где-что-лежит) (сверено по словам, совпадает).
- [Взгляд со стороны: рефлексия Claude](../../itmo/cs-masters/thesis/diary.html#reflect) — 28.10, ассистент о
  23–28.10: «шесть дней строили измерительный прибор», посредник, построенный тем, кто знает ответ; спуск по уровням
  (дерево → ревьювер → сводка → исследователь). В `nrhsi/docs` этого текста нет. Ответ автора (28.10): «НАМ И НУЖЕН
  ПРИБОР. имея прибор, мы подставим его в дерево и метод заработает. суть этого процесса сейчас -- в покопонентной
  отладке» (цитата — в разделе «изнутри», «Роль задаёт мерку»).
- [Взгляд изнутри: выборы автора](../../itmo/cs-masters/thesis/diary.html#inside) — 6.11 — тот же текст, что
  [REFLECT-INSIDE-1106](REFLECT-INSIDE-1106.md) (сверено по фрагментам); там же список поворотных точек 14.09–5.11.
- [Неясности и что не проверено](../../itmo/cs-masters/thesis/diary.html#unclear) — куски 1–8 (3.09–28.10): где
  источник неполон, числа не сверены. Читать вместе с числами этой страницы.

## 1. Тема и обзоры (4–11.09, 11.10, 15.10)

- [4.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-04), [5.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-05)
  — из ML свободны APO и ACE у Кулина; выбрана тема ACE, рук. Кулин. Дата решения — 04 или 05.09 (дневник, «Неясности», кусок 1).
- [6.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-06) — шаги 1–2 Кулина: обзоры ACE/SCOPE/DC, 39 PDF.
  Находка: две работы 2026 бьют по предпосылке ACE. Решение: воспроизвести ACE, SCOPE, DC на ornith-9b.
  Документы: [core-papers-ace-scope-dc](../../itmo/cs-masters/thesis/core-papers-ace-scope-dc.md),
  [literature-agent-memory](../../itmo/cs-masters/thesis/literature-agent-memory.md),
  [literature-prompt-opt-and-context](../../itmo/cs-masters/thesis/literature-prompt-opt-and-context.md),
  [analysis-pros-cons](../../itmo/cs-masters/thesis/analysis-pros-cons.md),
  [report-v2](../../itmo/cs-masters/thesis/report-v2.html), [memo-2026-09-06](../../itmo/cs-masters/thesis/memo-2026-09-06.html),
  [report-v2-annotated](../../itmo/cs-masters/thesis/report-v2-annotated.html).
- [7.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-07) — разбор compact-agent относительно обзоров —
  [compact-agent-review](../../itmo/cs-masters/thesis/compact-agent-review.html).
- [9.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-09), [10.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-10)
  — обзоры v3–v5 (11 + 10 + 30 работ): ACE как бейзлайн у других не лучший; у шести систем есть гейт перед записью,
  у ACE нет. [literature-v3-eleven](../../itmo/cs-masters/thesis/literature-v3-eleven.md),
  [literature-v4-ten](../../itmo/cs-masters/thesis/literature-v4-ten.md),
  [literature-v5-thirty](../../itmo/cs-masters/thesis/literature-v5-thirty.md),
  [candidates-v5](../../itmo/cs-masters/thesis/candidates-v5.md), отчёты [v3](../../itmo/cs-masters/thesis/report-v3.html)
  ([учебник](../../itmo/cs-masters/thesis/report-v3-textbook.html)), [v4](../../itmo/cs-masters/thesis/report-v4.html),
  [v5](../../itmo/cs-masters/thesis/report-v5.html). Формат обзоров (1/3 лёгкой + 2/3 строгой) — правило пользователя 9.09.
- [12.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-12) — сводка методов
  [ce-methods-summary](../../itmo/cs-masters/thesis/ce-methods-summary.md) (~90 записей); выбраны MCE, EvoLib, TF-GRPO.
- [11.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-11) — литература v6 (самоэволюция), ближайшая работа PACE,
  приёмка по ней 24/36; SAPO (первый автор — Кулин) — только ссылка.
  [literature-v6-self-evolution](../../itmo/cs-masters/thesis/literature-v6-self-evolution.md),
  [acceptance-pace](../../itmo/cs-masters/thesis/acceptance-pace.md),
  [pace-acceptance-results](../../itmo/cs-masters/thesis/pace-acceptance-results.md).
- [12.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-12) — разбор PromptAgent —
  [promptagent-review](../../itmo/cs-masters/thesis/promptagent-review.md).
- [15.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-15) — хэндофф терминологии «prompt / context / harness ×
  кто оптимизирует» ([handoff-terminology](../../itmo/cs-masters/thesis/handoff-terminology.md)); разборы
  [Meta-Harness, AHE](../../itmo/cs-masters/thesis/review-meta-harness-ahe.md),
  [MemoHarness, MemEvolve](../../itmo/cs-masters/thesis/review-memoharness-memevolve.md),
  [ACON, TRACE](../../itmo/cs-masters/thesis/review-acon-trace.md): оптимизатор ≤14B не проверял никто.
- [20.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-20) — карта литературы «уроки → малые модели» —
  [lit-lessons-small-models](../../itmo/cs-masters/thesis/lit-lessons-small-models.md).

## 2. Репликация ACE / SCOPE / DC и других (6–30.09)

Итог линии (дневник, карта сентября): ни один метод не отделился от baseline; 14.09 данные помечены черновиком; 27.09
прогоны «наших методов» признаны мусором; 10.10 всё прежнее по 9B — «мусор».
- [7.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-07) — MEB-40 слишком лёгкий (DC 38–40/40), лимит 2048 обрезал
  SCOPE и ACE → GPQA Diamond n=40, лимит 16384. Инцидент: 8 ч простоя из-за `pgrep -f`.
- [8.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-08) — GPQA-40, 9B: baseline 26, SCOPE 27, ACE 24→28, DC 27,
  DC cumulative 25; разнится только цена контекста (ACE ×20 к SCOPE). ACE online и SCOPE учатся на эталоне тестового
  потока, DC — без меток. `repro/RESULTS-gpqa-round2.md`.
- [9.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-09)–[11.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-11)
  — 27B и DeepSeek V4.1 Flash: ни один метод не выше baseline ни на одной из трёх моделей.
  [repro/RESULTS-gpqa-three-models.md](../../itmo/cs-masters/thesis/repro/RESULTS-gpqa-three-models.md),
  протокол [repro/PROTOCOL-context-opt.md](../../itmo/cs-masters/thesis/repro/PROTOCOL-context-opt.md).
- [12.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-12) — FiNER-40: few-shot из 5 (64,4%) не побил никто;
  GPQA с ручными плейбуками: прирост только у «full» с фактами из самих промахов (оракул, утечка). Решение: n=40
  вместо 200. [results-2026-09-12](../../itmo/cs-masters/thesis/results-2026-09-12.html),
  [repro/analysis-gpqa40-misses.md](../../itmo/cs-masters/thesis/repro/analysis-gpqa40-misses.md),
  [repro/misses-finer40.md](../../itmo/cs-masters/thesis/repro/misses-finer40.md).
- [13.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-13) — признание: у ACE, DC, SCOPE были три разных
  baseline-промпта → общий `common/tasks.py`. Шлюз не сэмплировал (TF-GRPO учился на копиях greedy) — починено.
  Схемы методов — [ce-architecture](../../itmo/cs-masters/thesis/ce-architecture.html).
- [14.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-14) — 6 методов на едином промпте: от −6 до +4 к greedy,
  устойчивого прироста нет; баг ACE: пустой `bullet_usage_log`. Решение пользователя: остановить прогоны, данные —
  черновик, «пройтись глазами по всем методам».
- [15.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-15) — библиотека SVG-карточек схем (`thesis/diagrams/`),
  [ce-architecture-handmade-v4](../../itmo/cs-masters/thesis/ce-architecture-handmade-v4.html),
  [ce-architecture-mermaid-v3](../../itmo/cs-masters/thesis/ce-architecture-mermaid-v3.html).
- [17.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-17), [18.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-18)
  — «хватит играться»: 8 проблем стенда; дизайн «курируемая память с гейтом по исходам» (создан ли `prototype-design.md`
  и отправлено ли письмо Кулину — дневник не уверен).

## 3. Свой стенд `~/Projects/ace` и верность апстриму (21–30.09)

- [21.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-21) — встреча с Кулиным: тема на троих (с Никитой);
  вехи Кулина — 31.10 метод и эксперименты, 31.12 статья. Решение: «одна реализация цикла, свой харнесс, чужие задачи».
- [22.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-22) — за ночь стенд ace (54 коммита): formula40 все в
  коридоре 24–29 при базе 27. Находка: методы местами «воспроизводили догадку» →
  [PLAN-fidelity](../../itmo/cs-masters/thesis/PLAN-fidelity.md), [ce-replication](../../itmo/cs-masters/thesis/ce-replication.html).
- [23.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-23), [24.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-24)
  — библиотека по уровням, хуки; построчное ревью кода пользователем (REVIEW.md); метод как набор хуков (SKETCH.md).
- [25.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-25) — уровни методов ([vision](../../itmo/cs-masters/thesis/vision.html),
  [vision-levels](../../itmo/cs-masters/thesis/vision-levels.html)); новый критерий верности: запись апстрима на 9B
  и побайтный replay. Отсюда позже детерминизм стенда и rerun (→ [приборы](instruments.md)).
- [26.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-26) — стенд по уровням, GEPA: replay 20/20 побайтно;
  аудит верности: DC без исполнения кода, SCOPE с утечкой ответа. Решение: «чинить, а не документировать».
  [ce-stand](../../itmo/cs-masters/thesis/ce-stand.html).
- [27.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-27) — раунд 3: ACE 26/40 = ace_e0, сигнала пользы нет;
  «единственное value — прогоны апстримов», очередь наших методов — мусор.
- [28.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-28) — критерии «честного прироста» до цифр; мощность при
  n=40 ≈ эффект 20 п.п.
- [29.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-29), [30.09](../../itmo/cs-masters/thesis/diary.html#d2026-09-30)
  — стенд ужат ~22,7 → ~1,7 тыс. строк, апстримы — подмодули; правило: выбор по эталону не используется; записи
  апстримов (DC, EvoLib HMMT, ACE no-GT, GEPA, SCOPE, tfgrpo_nogt).
- Файлы стенда тех дней (PLAN.md, REVIEW.md, SKETCH.md, CONSTRUCTION.md, REPORT.md) — в `~/Projects/ace/`; та ли там
  версия, что в дневнике, не сверял.

## 4. Новая постановка и AppWorld (4–20.10)

- [4.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-04), [7.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-07)
  — из BlueSec: идея «рефлектор по фактам» ([notes-bluesec-2026-10-04](../../itmo/cs-masters/thesis/notes-bluesec-2026-10-04.md));
  терминология для текста.
- [10.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-10) — поворот: прежние результаты по 9B — «мусор»; 9B сама
  правит свой контекст, правку принимает A/B, сильной модели в цикле нет. Кандидаты датасета —
  [datasets-examples](../../itmo/cs-masters/thesis/datasets-examples.md).
- [11.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-11), [12.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-12)
  — приёмка по сигналу на 3 роллаутах; дерево: узел = хэш харнесса, PUCT (→ [метод](method.md)).
- [15.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-15) — созвон с научником: ниша CONTEXT × AGENTIC (правка
  только O), прежнее дерево отложено; датасет AppWorld; smoke — 9B решила 1 задачу dev.
- [16.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-16) — «харнесс (код) 9B отдавать не хочу»; первый
  dev-прогон позже признан невалидным.
- [17.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-17) — оценка AppWorld была сломана (SQLAlchemy 2.1), старый
  воркер шёл с presence_penalty 1.5: ранние цифры невалидны. Валидная база dev 12/57, GPT-4o ReAct 29/57. Прокси v1 11,
  v2 30, v3 30: прирост — PROMPT, а не O.
  [appworld-9b-trace-review](../../itmo/cs-masters/thesis/appworld-9b-trace-review.md),
  [appworld-9b-trace-review-1017](../../itmo/cs-masters/thesis/appworld-9b-trace-review-1017.md),
  [proxy-v2](../../itmo/cs-masters/thesis/appworld-proxy-v2.md), [v2-trace-review](../../itmo/cs-masters/thesis/appworld-v2-trace-review.md),
  [proxy-v3](../../itmo/cs-masters/thesis/appworld-proxy-v3.md), [proxy-v4](../../itmo/cs-masters/thesis/appworld-proxy-v4.md).
- [18.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-18) — v4 (только O) 10/57: чистый O прироста не даёт;
  v7 (9B правит свою инструкцию) 20 / 20 / 15 — без отбора не сходится. [proxy-v5](../../itmo/cs-masters/thesis/appworld-proxy-v5.md).
- [19.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-19) — шум: нейтральная правка 15/57 (13 переворотов);
  v9 (агент Claude) 37/57, v9np 38. «Из этого пока не сделать метод». Детерминизм не зависит от числа потоков.
  [proxy-v9](../../itmo/cs-masters/thesis/appworld-proxy-v9.md).
- [20.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-20) — скачок v2 12→30 дала починка кода демо; правки 9B
  цитируют задачи dev; судья-9B best-of-k почти ничего не добавляет. Линия «9B пишет харнесс через лабу» свёрнута.
  Постановка автора: малым моделям лишний контекст вредит, надёжного способа передать уроки нет.
  [appworld-harness-review](../../itmo/cs-masters/thesis/appworld-harness-review.md).

## 5. Перенос на train, атрибуция, дерево v1–v3 (21–24.10)

- [21.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-21) — train 90 (отложенный): база 15, v9np 50; формы
  уроков trig 31, text 24, demo 23. Поворот: атрибуция вины частям промпта, Δlog p как prior для PUCT.
  [v9np-train-review](../../itmo/cs-masters/thesis/appworld-v9np-train-review.md),
  [forms-train-review](../../itmo/cs-masters/thesis/appworld-forms-train-review.md),
  [appworld-runs-report](../../itmo/cs-masters/thesis/appworld-runs-report.html),
  [method-design-challenge](../../itmo/cs-masters/thesis/method-design-challenge.md),
  [method-related-work-deep](../../itmo/cs-masters/thesis/method-related-work-deep.md) (37 статей).
- [22.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-22) — абляции train: демо v2 49, правила 34, вместе 47
  (49 и 34 выведены из «+34/+19 к базе», итоговых строк нет — дневник, «Неясности», кусок 7). tree1 ничего не нашло,
  испорчено образцом id «21.3» в промпте. Решение: дерево v2, IFBench вторым бенчем.
  [appworld-tree1-review](../../itmo/cs-masters/thesis/appworld-tree1-review.md).
- [23.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-23) — дерево v2: 25 листов, глубина почти не растёт;
  перезамер на 40: проклятие победителя (+8/20 → +4/40). Prior Δlog p с исходом не связан → «лучше тогда рандом»,
  равномерный prior в v3. Ревьювер дерева: в 66 из 69 вызовов без трасс пишет «the trace shows».
  [appworld-prior-notes](../../itmo/cs-masters/thesis/appworld-prior-notes.md),
  [tree2-reviewer-review](../../itmo/cs-masters/thesis/appworld-tree2-reviewer-review.md),
  [Self-Harness](../../itmo/cs-masters/thesis/papers/reviews/2606.09498-SelfHarness.md).
- [24.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-24) — трассы корня при T=0 совпали дословно; tree3b
  остановлен: «правки у нас основаны на ревьювере, так?» — нет, вслепую. Валидатор очищен от проверки «код парсится»
  («чистой воды читинг»).

## 6. Пробы ревьювера, загрязнения, новизна, исследователь fsr (24–28.10)

Главная тема — [исследователь](reviewer.md); здесь до репозитория NRHSI.
- [24.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-24) — пробы ревьювера A/B/C: сводка кодом по 90 трассам
  лучше трёх трасс; 9B находит причины, но пишет правки плохо.
  [appworld-reviewer-probes-1024](../../itmo/cs-masters/thesis/appworld-reviewer-probes-1024.md),
  [Harness²](../../itmo/cs-masters/thesis/papers/reviews/2610.14224-Harness2.md),
  [Harness-R1](../../itmo/cs-masters/thesis/papers/reviews/2608.02276-HarnessR1.md).
- [25.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-25) — ACE no-GT на AppWorld не видит об исходе ни бита.
  Три задачи ревьювера (автор): что пошло не так, какая часть промпта виновата (или никакая), как исправить.
- [26.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-26) — аудит загрязнений (40 находок, семь классов);
  «линтер для кода харнесса — ожидаемо, линтер для содержимого бенчмарка — своего рода оракул»; честная база: пагинация
  пропала. Тема: «нет научной новизны», атрибуция провалов «слишком далеко от лабы Кулина».
  [appworld-probes-contamination-1026](../../itmo/cs-masters/thesis/appworld-probes-contamination-1026.md),
  [failure-attribution-1026](../../itmo/cs-masters/thesis/papers/reviews/failure-attribution-1026.md).
- [27.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-27) — новизна: свободно только сочетание признаков
  ([topic-novelty-1026](../../itmo/cs-masters/thesis/papers/reviews/topic-novelty-1026.md) §5–6); r3–r9: «все
  текущие варианты плохие», сито убрано; факты стенда (контекст 65536, нативный tool calling); исследователь трасс на
  9B с bash; ядро метода и оси абляции; песочница v3a. Письмо научруку (дата отправки неизвестна).
- [28.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-28) — песочница v3c (deny default), матрица контекста v3b
  (итогов нет на момент записи); «своего замера прироста на AppWorld нет». Журналы `scratchpad/reviewer_probe/`
  (fsr/journal.md, STAND.md) — вне `thesis/`.
- Разборы 28.10, на которые дневник не ссылается:
  [method-project](../../itmo/cs-masters/thesis/method-project.html) (проект метода),
  [fresh-look-1028](../../itmo/cs-masters/thesis/fresh-look-1028.md) («NRHSI: свежий взгляд со стороны»),
  [novelty-argument-1028](../../itmo/cs-masters/thesis/novelty-argument-1028.md) («достаточна ли новизна»),
  [benchmarks-candidates](../../itmo/cs-masters/thesis/benchmarks-candidates.md) («второй бенчмарк: где меряются
  конкуренты»). Описание — по их заголовкам.
- [29.10](../../itmo/cs-masters/thesis/diary.html#d2026-10-29) — конкуренты: Self-Harness (прямой), Harness-R1
  (почти прямой), [competitors-vs-nrhsi-1029](../../itmo/cs-masters/thesis/competitors-vs-nrhsi-1029.md). Дальше —
  репозиторий NRHSI ([ход работы](MAP.md#где-что-лежит)).

## Хвосты, оставшиеся без отметки

Перенесены из прежнего трекера. Линии, к которым они относятся, дневник называет свёрнутыми: репликация — «мусор»
10.10, «9B пишет харнесс через лабу» — 20.10, пробы со сводкой — «все текущие варианты плохие» 27.10. О закрытии самих
пунктов дневник не пишет.

- 12.09 — перепрогон DC cumulative на FiNER-40 отложен на после фаз.
- 13.09 — порядок в `repro/` (vendor/common/adapters/tools/queues/results/README) после фазы 4.
- 14.09 — в будущих прогонах ACE — `--json_mode`, не патч регекспа.
- 22.10 — trig0 (нейтральная пометка, контроль для trig=31) не запускался; IFBench выбран для сравнения с GEPA/AgentGrad
  и PACE, вторым бенчем позже стал ALFWorld — что с IFBench, источник не говорит.
- 26.10 — гипотеза про удалённую фразу-таксономию не проверена; срок согласования темы в `status.json` — 31.10.
- 28.10 — матрица v3b (контекст исследователя): итогов нет, очередь B1 остановлена после 2 сессий из 27.
