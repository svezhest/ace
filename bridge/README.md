# Мостик к апстримам: эталоны

Эталоны сняты с чистых HEAD апстримов на фейковой модели. По ним тесты `tests/bridge/` будут сверять
наш код с апстримами. Сами тесты пишутся после переписывания `ace/`.

## Окружения

```sh
bridge/setup_envs.sh            # все; или: bridge/setup_envs.sh ace mce youtu light
```

Скрипт делает `git worktree add --detach` апстримов из `repro/` в `$UPSTREAMS` (по умолчанию
`/Users/user/Projects/upstreams`) на коммитах ниже и ставит venv в `$UPSTREAMS/.venvs/`. Где есть
`uv.lock`, зависимости ставятся из него, сам проект не ставится. Рабочие копии в `repro/` не трогаются:
у ace и dynamic-cheatsheet там локальные правки.

| метод  | апстрим                  | коммит  | venv  |
|--------|--------------------------|---------|-------|
| ace    | ace                      | 82709de | ace (lock, torch) |
| dc     | dynamic-cheatsheet       | 5cfe3c3 | light |
| scope  | SCOPE                    | 4dc0da5 | light |
| evolib | EvoLib                   | 98266b2 | light |
| tfgrpo | youtu-agent              | c2caa53 | youtu (lock) |
| mce    | meta-context-engineering | c4b7a7c | mce (lock) |

## Снятие эталонов

Все команды запускаются из корня стенда. Каждая занимает секунды, реальных вызовов модели нет.

```sh
U=/Users/user/Projects/upstreams/.venvs
$U/ace/bin/python   bridge/capture_ace.py
$U/light/bin/python bridge/capture_dc.py
$U/light/bin/python bridge/capture_scope.py
$U/light/bin/python bridge/capture_evolib.py
$U/youtu/bin/python bridge/capture_tfgrpo.py
$U/mce/bin/python   bridge/capture_mce.py
```

Каждая команда пишет `bridge/fixtures/<метод>/*.json` в виде `{"header": ..., "data": ...}`. В `header`
указаны репозиторий, путь, полный коммит, `file:line` каждой вызванной функции апстрима, команда и
версия python. Повторный запуск даёт побайтно те же файлы, это проверено на всех шести.

Уровни (не у каждого метода есть все):

- `prompts` — сырые шаблоны и реальные запросы, которые записал фейк: messages, temperature,
  max_tokens, response_format;
- `parsers` — разборщики ответов модели на неудобных входах;
- `memory` — операции над памятью;
- `loop` — цикл на 3–7 задачах;
- `eval`/`evals` — чекеры задач;
- дополнительно: `dc/cheatsheet_compare.json` (сравнение HEAD, repro-патча и нашего кода) и
  `tfgrpo/config.json` (конфиг агента, как его собирает utu).

`fake.py` пишет каждый запрос и отвечает заготовкой. Ответ выбирается по маркеру в тексте промпта или по
хэшу промпта, а не по номеру вызова. Фейк никогда не бросает исключений. `fake.offline()` задаёт
`TIKTOKEN_CACHE_DIR=$UPSTREAMS/.tiktoken`, фиктивные ключи, seed и пустой tmp-каталог как cwd.

## Ловушки

- **Порядок:** порядок снятия важен. Сначала `offline()`, потом импорт апстрима: `load_dotenv`
  (у DC `config.env`, у MCE `override=True`) ищет файлы в cwd.
- **Файлы апстримов:** всё, что пишут апстримы, уходит в tmp. Пути в данных заменены на
  `<TMP>`/`<REPO>`, время — на `<ts>`.
- **Параллелизм:** ACE — `test_workers=1`. TF-GRPO — `as_completed` по порядку создания. EvoLib и
  SCOPE — последовательно.
- **Замены, которые не из апстрима:**
  - EvoLib: вместо matharena `eval_function` стоит наш строковый чекер по `<answer>` (помечено в шапке);
  - TF-GRPO: utu замещён шимом из `repro/tfgrpo_run.py:58-140`, хотя utu импортируется и без него;
  - MCE: агенты Claude SDK заменены заготовками, а валидация и очистка workspace — настоящие.
- **youtu-agent:** при импорте utu создаёт `logs/` в worktree, git его игнорирует.

## Подозрения и результат

**Подтвердились:**

- **formula: `$` и строковое сравнение.** Проверка в `eval/finance/data_processor.py:153-161`:
  - `$15.00` против `15.0` даёт False;
  - нечисловые ответы сравниваются как строки. (`ace/eval.json`)
- **finer: сравнение через eval против float.** Проверка в `data_processor.py:126-151`:
  - True дают `1+1`=`2` и `0.5`=`1/2`;
  - `$` снимается только с ответа модели;
  - `$1,200` против `1200` даёт False, потому что ответ сначала режется по запятой. (`ace/eval.json`)
- **ACE: регулярка bullet_ids.** Регулярка `\[([a-z]{3,}-\d{5})\]` (`ace/core/generator.py:115`, `_extract_bullet_ids_regex`) не
  ловит:
  - `[ph-00003]`;
  - верхний регистр;
  - JSON-список `["calc-00001"]`.

  В json_mode список в кавычках приходит строкой. (`ace/parsers.json`)
- **ACE: slug `ph`.** `get_section_slug` (`utils.py:53`) даёт `ph`. Раздел под другим написанием уходит
  в OTHERS (`playbook_utils.py:108-150`). В цикле цитируемый `ph-00002` остаётся со счётчиками 0/0.
  UPDATE, DELETE и MERGE curator молча игнорирует. (`ace/memory.json`, `ace/loop.json`)
- **SCOPE: жёсткий порог 0.85.** Порог зашит в `scope/strategic_store.py:201`.
  `strategic_confidence_threshold` (`optimizer.py:79`) до хранилища не доходит:
  - при threshold=0.7 правило с 0.8 возвращается как strategic, но в память не попадает;
  - 0.8499999 отвергается, 0.85 принимается. (`scope/memory.json`)
- **SCOPE: глобальный лимит 20.** `max_rules_per_task=20` считается по `_applied_rules_count[agent]`
  (`optimizer.py:206-208`, `:528`), и счётчик не сбрасывается между задачами. Задачи 21 и 22 получают
  None, хотя синтезатор и классификатор всё равно вызываются. (`scope/memory.json`)
- **DC: пропатченный extract_cheatsheet.** HEAD (`dynamic_cheatsheet/utils/extractor.py:62-87`) берёт
  текст блока. Патч в repro (`extractor.py:82-84`) возвращает старую шпаргалку в трёх случаях:
  - в тексте есть `[Version Number]`;
  - в тексте есть `<memory_item>\n[...]`;
  - длина меньше 300.

  Поэтому на коротких шпаргалках патч расходится с HEAD. Наш `ace/parse.py:13-17` совпадает с HEAD,
  кроме случая, когда второй `<cheatsheet>` стоит до первого `</cheatsheet>`: HEAD режет по второму
  тегу, мы включаем его в текст. (`dc/cheatsheet_compare.json`)
- **MCE: train перезаписывается батчем.** `data/train.json` под-итерации содержит только текущий батч
  (`mce/main.py:259-265`), `data/` между под-итерациями не копируется (`mce/utils.py:356-386`), train
  выбирается заново на каждой итерации (`main.py:132`). (`mce/loop.json`)
- **TF-GRPO: температура в eval.** Rollout в обучении идут при T=0.7 (`utu/practice/training_free_grpo.py:84`).
  Eval внутри обучения делит с ними агента (поверхностный `model_copy`, `:81`, `:93`) и тоже идёт
  при 0.7. Итоговый агент — T=0.3, top_p=0.95 (`:248`, `configs/agents/practice/math_agent.yaml`).
  У нас в `ace/methods/tfgrpo.py:11` T=0, это расхождение. Updater в апстриме температуру не шлёт
  (`model_params={}`), а repro шлёт 0.0. (`tfgrpo/config.json`)

**Опровергнуто:**

- **MCE: откат к iter0.** iter0 в `evaluations.json` не пишется (`mce/main.py:115`), а по умолчанию
  цикл стартует с iter1 (`main.py:423`). iter0 как источник берётся только на iter1
  (`mce/utils.py:438-447`). Дальше берётся лучшая из iter≥1, даже если все хуже baseline. При равенстве
  побеждает первая: сравнение строгое (`utils.py:476`). (`mce/memory.json`)

**Не проверялись здесь:** meb ×÷ и чекеры meb/gpqa — наши, у апстримов их нет. Но DC
`eval_equation_balancer` не принимает `×`/`÷` против `*`/`/` (`dc/evals.json`).

## Попутные находки (видны в эталонах)

- **EvoLib:**
  - IG — это мера разногласия `log(best) − log(mean)` (`evolib_agent.py:219`, `:355`).
  - Штраф ×0.5 (`:366-369`) работает так:
    - срабатывает только при непустом инсайте;
    - IG считается до штрафа;
    - режет баллы до проверки улучшения и future IG.
  - Порог слияния 0.8 строгий (`:153`, `:189`).
  - Одна функция без докстринга обнуляет результат `extract_functions` (`utils.py:23`).
  - `is_better_solution` засчитывает «Solution 1 is better than solution 2» решению 2.
- **SCOPE:** классификатор не вытаскивает `{...}` из окружающего текста и падает на
  `"confidence": "high"` (откат на tactical). `GuidelineHistory.get_statistics` считает по task_id
  (`history_store.py:242`).
- **TF-GRPO:**
  - `<Experiences>` без закрывающего тега даёт "".
  - Ограда `` ```JSON `` или `` ``` `` без `json` выбрасывает группу.
  - UPDATE с неизвестным id добавляет запись.
  - Объект вместо списка роняет `_batch_update`.
- **MCE:** в промпте мета-агента метрика истории — первый ключ `val_metrics`, а не
  `get_primary_metric_name` (`mce/prompts/meta_agent.py:217`).
