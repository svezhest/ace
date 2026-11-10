# Карта кода и журналов на 10.11 (HEAD c2e612a)

> **Состояние на c2e612a, до чистки.** После a13b543 в коде осталась одна база: флагов из таблиц ниже, кроме служебных, в `cli.py` нет, скриптов с пометкой «нет» — тоже. Что убрано и где листинг — `docs/REMOVED-1110.md`. Ссылки «файл:строка» на код — по c2e612a (`git show c2e612a:ФАЙЛ`); ссылки на строки журналов (L03, L09, L10, EJ) пересчитаны после вставки листингов в журналы. Потом журналы разложены по пробам (`docs/lab/`): ссылка L03/L09/L10 ведёт в файл пробы или дня, где теперь лежит эта строка; номер — по 728e61b (`git show 728e61b:docs/LAB-1103.md`), внутри файла его видно по отметке `<!-- LAB-1103.md:N–M -->`.

Собрано агентом только чтением 10.11 по запросу автора: «где посмотреть актуальный код без мёртвых веток, на что
ссылается каждая LAB». Ссылки «файл:строка» проверены выборочно (правки `rerun_writer.py` 10.11 — подтверждено по
`git log`); перед удалением кода по этой таблице сверять.

Всё сделано только чтением, модель не запускалась. Обозначения: «L03» — строка `docs/LAB-1103.md`, «L09» — `docs/LAB-1109.md`, «L10» — `docs/LAB-1110.md` (номера по 728e61b, ссылки — на файлы `docs/lab/`), «EJ» — `editor/JOURNAL.md` (лежит не в docs/, но там записаны пробы 29–30.10). Итоги проб даны в виде V/P/B/x на 10 сессий. В столбце «код» — число строк с именем: `a.<attr>` в `cli.py` и `C.<ИМЯ>` или `getattr(C,"ИМЯ")` в остальных файлах `nrhsi/editor/*.py`. В `editor/*.py` имён cfg нет ни одного.

## 1. Флаги `nrhsi/editor/cli.py` (55 штук)

**Базовые и служебные**

| флаг | проба | постановка → итог | итог (числа) | пометки о браке | статус | код |
|---|---|---|---|---|---|---|
| --rerun | W1 | [L03:499–507](lab/1104/W-writer-variants.md) (3–4.11, 53b3ddc) → [L03:529](lab/1104/W-writer-variants.md) | W1 2/2/1/5 против W0 2/1/1/6; «по счёту не лучше» | [L03:522–523](lab/1104/W-writer-variants.md): первые 10 сессий W1/W2 перезапущены с новой формулировкой; [L03:542](lab/1104/W-writer-variants.md): даты в `ls -la` разводили пары; [L03:684](lab/days/1104.md): «298 rerun» — ошибка счёта | в базе | cli 14; C.RERUN gate 2, phase 1, work 5 |
| --auto-check | AC | [L03:689](lab/1104/ST-AC-RT-SC-blocks.md), [693](lab/1104/ST-AC-RT-SC-blocks.md) (4.11, 65475f2) → [L03:938](lab/1104/ST-AC-RT-SC-blocks.md), [1075](lab/1104/ST-AC-RT-SC-blocks.md) | AC 2/1/4/3 против W1 2/2/1/5; AC_s2 1/0/3/6; «ни один не поднял V» | — | в базе | cli 7; tools 1, gate.edit_checks (21 стр.) |
| --ticket | TK | [L03:1960–1986](lab/1106/TK-TKS-ticket.md) (6.11, b8f8e4e) → [L03:2034–2062](lab/1106/TK-TKS-ticket.md) | TK 0/0/3/7 | [L03:2062](lab/1106/TK-TKS-ticket.md) «мой брак» (текст ModuleNotFoundError, задета 1 проверка из 39) | в базе | cli 5; C.TICKET gate 5; ticket_check 96 стр. |
| --ticket-show | TKS | [L03:2006–2009](lab/1106/TK-TKS-ticket.md) (1c3a6e5) → [L03:2050](lab/1106/TK-TKS-ticket.md), [2512](lab/1106/TKV-values.md) | TKS 2/2/0/6; за 3 seed 4/6/7/13 | [L03:2290](lab/1106/TKC-TKR-cover.md), [2809](lab/days/1106.md): у TKS s1 и TKS_s2 04–09 конфаунд — менялась длина `rerun_core.py` | в базе | cli 2 (+ функция cli.ticket_line) |
| --ticket-line | TKL | [L03:2334–2351](lab/1106/TKL-ticket-line.md) (d57c22f) → L03:2414–2431 ([TKL](lab/1106/TKL-ticket-line.md), [TKF](lab/1106/TKF-ticket-first.md)) | 1/2/0/7 против TKS 2/2/0/6; факт принят в 2 из 3 показов (таблица TKC — 0 из 10) | — | в базе | cli 4; gate 1; _dead_fact 42 стр. |
| --ticket-values | TKV | [L03:2386–2400](lab/1106/TKV-values.md) (e92b6a7) → [L03:2445–2464](lab/1106/TKV-values.md), [2512](lab/1106/TKV-values.md) | 1/1/1/7; за 3 seed 3/5/5/17 против TKS 4/6/7/13; значения приняты 3 из 3 | [L03:2480](lab/1106/TKV-values.md) «мой брак»: операнд вычислялся вне короткого замыкания, задеты TKV s1 и TKVB (исправлено в 69e3d91). [L10:800–814](lab/1110/AA-ticket-all-any.md) (c2e612a, all/any): «Не замерено» | в базе | cli 5; gate 2; _operands, _safe, _watch и др. ≈92 стр. |
| --ticket-why | TKW, затем TKD | [L03:2555–2572](lab/1106/TKW-why.md) (2df0de8) → [L03:2730](lab/1106/TKW-why.md), [2976](lab/1106/TKD-why-no-key.md) | TKW 5/4/4/17 против TKV 3/5/5/17; от механизма одна V (06_s2, перекрытый def); TKD 5/4/4/17 | [L03:2837](lab/1106/TKW-why.md) «нет ключа» — **«Подгонка, убрано»** (74e8460); [L03:2990](lab/1106/TKD-why-no-key.md) «подтверждает, что правило было подгонкой» | в базе (без правила ключа) | cli 4; gate 1 + `__shape__`; _shadowed и _why_fact 33 стр. |
| --clean | PL (+CL) | L03:3024–3043 ([6.11](lab/days/1106.md), [PL](lab/1106/PL-plain-clean.md)) (59ea5e9), [L03:3108–3119](lab/1106/PL-plain-clean.md) (768f357) → [L03:3258–3272](lab/1106/PL-plain-clean.md) | PL 4/2/8/16 против TKD 5/4/4/17 — шум | [L03:3110](lab/1106/PL-plain-clean.md): первый вариант ответа на повтор — «был ошибкой» | в базе | cli 4; C.CLEAN phase 1, tools 2 |
| --input-text | P7 (затем все серии wv) | [L03:414](lab/1103/P7-ideal-input.md) (880efd9) → [L03:419–430](lab/1103/P7-ideal-input.md) | на идеальных входах 5/5 применено дословно | [L03:463](lab/days/1103.md): «P7 — во входах был готовый код»; [L03:490](lab/1103/S12-manual-inputs.md): §12–13 (ручные входы через этот флаг) «недействительны» | служебный | cli 3 |
| --bench, --input, --arm obs, --view, --seed, --tag, --stand, --home, --rlogs, --lint, --dry | — | — | — | — | служебные | — |

**Остальные флаги — кандидаты в «осталось от проб»**

| флаг | проба | постановка → итог | итог (числа) | пометки о браке | статус | код |
|---|---|---|---|---|---|---|
| --arm fix | B1 | EJ:3 (29.10); NIGHT-1029:9 | obs ≈ fix (хороших 14–19 %), fix ломает чаще: 5/8 против 2/8 → выбран obs | — | без эффекта | cli.propose_step (18 стр.), PROPOSER_T |
| --arm merge | P4 | [L03:312–319](lab/1103/P4-merge.md) (3d9cf44) → [L03:435](lab/1103/P4-merge.md) | 2 сессии: s2 верна, s1 потеряла механизм | [L03:439](lab/1103/P4-merge.md) «Ошибка» (слияние поставлено на val), [L03:463](lab/days/1103.md) «P4 — 2 попытки» | не замерен по сути | inputs.first_user_merge, editor/merge3.py |
| --predict | LP, ветка pred дерева | EJ:431 (30.10, 6991d56) → EJ:443; NIGHT-1101:106 | «--predict не выполняется»: реплик с ожиданием 0–2 против 0–1; pred — 11 живых из 62, obs — 15 из 86 | NIGHT-1101:104: разница вариантов смешана с разницей узлов | без эффекта | cli 2; PREDICT_LINE |
| --cite | P1 | [L03:51–59](lab/1103/P1-cite.md) (3.11, e4924d3) → [L03:61–69](lab/1103/P1-cite.md); READ-writer-1103:31 | cite 30/40 применено против obs 27/32; «цитата использована» App 6/16, ALF 0/12 | [L03:69](lab/1103/P1-cite.md) «мерка негодна для ALF… снята»; [L03:70](lab/1103/P1-cite.md) «Дефект 1» (сессии стёрты); [L03:413](lab/days/1103.md) замер на задачах снят; [L03:463](lab/days/1103.md) | испорчен / снят | cli 2; inputs ≈8 |
| --import-src | P2 | [L03:123–128](lab/1103/P2-import-src.md) (c0775da) → [L03:130–131](lab/1103/P2-import-src.md) | python3 с импортом: imp 5 из 6, obs 4 из 6; «флаг его не усилил» | [L03:463](lab/days/1103.md) «не проверил до пробы»; **[L03:1090](lab/days/1105.md): исход по построению** | без эффекта | cli 2; IMPORT_LINE |
| --smoke-calls | P6 | [L03:148–154](lab/1103/P6-smoke-calls.md) (7a6f00d) → [L03:434](lab/1103/P6-smoke-calls.md); READ-writer:38 | строки вызовов не использованы ни разу; поломано 1 из 6, пусто 1 | — | без эффекта | cli 2; C.SMOKE_CALLS work 2 |
| --goal-text | W10 | [L03:516](lab/1104/W-writer-variants.md) (e1031fa) → [L03:530](lab/1104/W-writer-variants.md) | 2/0/2/6 — «не лучше W0/W1» | — | без эффекта | cli 2; turn 3 |
| --goal-k | W2 | [L03:511](lab/1104/W-writer-variants.md) (70ed854) → [L03:528](lab/1104/W-writer-variants.md) | 1/0/2/7 (из них 2 без правок) | **[L03:542](lab/1104/W-writer-variants.md): цель приходила до первой правки в 7 из 10 — «посылка ложная»**; пары W1/W2 разводил `ls -la` | без эффекта | cli 4; phase 1 |
| --rerun-at | W14 | [L03:518](lab/1104/W-writer-variants.md) (bda5669) → [L03:531](lab/1104/W-writer-variants.md) | 2/0/1/7, «не лучше»; [L03:2953](lab/days/1106.md) «не принят» | — | без эффекта, **но `--at` с c918594 стоит в README всегда** ([L10:19](lab/1110/TY-typed-hooks.md)) | cli 5; C.RERUN_AT только присваивается, нигде не читается |
| --finish-review | W15 | [L03:519](lab/1104/W-writer-variants.md), [525](lab/1104/W-writer-variants.md) (35e1a45) → [L03:532](lab/1104/W-writer-variants.md) | 2/1/2/5, как W1; `submit=false` — 0 из 19 показов | [L03:530](lab/1104/W-writer-variants.md) дыра «обзор не показывается при forced»; **[L03:542](lab/1104/W-writer-variants.md), [1092](lab/days/1105.md): W1 и W15 не парные по построению** | без эффекта | cli 4; gate 2, schema 1; review_text |
| --temp | W17 | [L03:520](lab/1104/W-writer-variants.md) → [L03:533](lab/1104/W-writer-variants.md) | 2/1/1/6, как остальные | — | без эффекта | cli 2; F.TEMP |
| --bash-limit | W1L, TKVB | [L03:683](lab/1104/W1L-bash-limit.md) (b5b7ab7) → [L03:891–895](lab/1104/W1L-bash-limit.md), [1070](lab/1104/W1L-bash-limit.md), [2471](lab/1106/TKVB-bash40.md) | вердикты от L не зависят (L≤25: V5 B2 x2; L≥30: V5 x3); TKVB 2/1/2/5 против TKV 1/1/1/7 | [L03:2886](lab/days/1106.md): «весь бюджет при любом лимите» — неверно | без эффекта | cli 3; C.BASH_LIMIT ×5 файлов |
| --checked | P3, C30 | [L03:275–281](lab/1103/P3-checked.md) (c0775da) → [L03:282](lab/1103/P3-checked.md), [937](lab/1104/ST-AC-RT-SC-blocks.md) | C30: V4 P1 B2 x9 против ST V4 P3 B6 x5 | **[L03:1091](lab/days/1105.md), [1095](lab/days/1105.md): «вслепую 0» — ноль по построению**; READ-writer:36: полуприменённое изменение | без эффекта | cli 5; phase 1, tools 1 |
| --stages | ST, STAC | [L03:688](lab/1104/ST-AC-RT-SC-blocks.md), [693](lab/1104/ST-AC-RT-SC-blocks.md) (65475f2) → [L03:937](lab/1104/ST-AC-RT-SC-blocks.md), [1074](lab/1104/ST-AC-RT-SC-blocks.md) | ST V4 против C30 V4; STAC 2/0/1/7 ×2 | **[L03:897–899](lab/1104/ST-AC-RT-SC-blocks.md) «Ошибка»: правки после конца bash применялись** (e03ea7b), 00–02_ST_s1 отложены как STnochk; [L03:1095](lab/days/1105.md) | без эффекта, замер исправлен перезапуском | cli 5; STAGES phase 4, tools 3, state 1 |
| --check-auto-only | CL | [L03:2902](lab/days/1106.md), [2917](lab/1106/CL-check-auto-only.md) (baa52c4) → [L03:3209–3224](lab/1106/CL-check-auto-only.md) | 3/0/2/5 против TKD s1 1/1/1/7; процесс не сдвинулся (ручной rerun 14 % против 14 %) | — | в базе через --clean | cli 3; CHECK_AUTO_ONLY_LINE |
| --no-trust | NT | [L03:3274–3283](lab/1106/NT-no-trust.md) (2b874c8) → [L03:3334–3346](lab/1106/NT-no-trust.md) | 6/3/8/13 против PL 4/2/8/16 — шум; чтения logs/ не больше | 00 s1 V? «за автором» | без эффекта | cli 2; NO_TRUST_ARM |
| --rerun-tool | RT, RT2 | [L03:690](lab/1104/ST-AC-RT-SC-blocks.md) (65475f2), [L03:943–945](lab/1104/ST-AC-RT-SC-blocks.md) (7ce7f2f) → [L03:938–939](lab/1104/ST-AC-RT-SC-blocks.md), [1053–1056](lab/1104/ST-AC-RT-SC-blocks.md) | RT 1/0/3/6; RT2 — 2 сессии, «failed» не выпал ни разу | [L03:944](lab/1104/ST-AC-RT-SC-blocks.md): «ложное подтверждение» — неверно; [L03:946](lab/1104/ST-AC-RT-SC-blocks.md): RT2 стартовали со старым кодом, остановлены | без эффекта / RT2 по сути не замерен | cli 10; C.RERUN_TOOL ×4 файла |
| --scratch | SC | [L03:691](lab/1104/ST-AC-RT-SC-blocks.md) → [L03:938](lab/1104/ST-AC-RT-SC-blocks.md), [1075](lab/1104/ST-AC-RT-SC-blocks.md) | SC 2/0/2/6; SC_s2 1/1/1/7 | — | без эффекта | cli 4; work 1, schema 1 |
| --tools-dir | TD, TU | [L03:953–956](lab/1105/TD-TU-HT-tools-dir.md) (962c522) → L03:1064–1080 ([TD, TU, HT](lab/1105/TD-TU-HT-tools-dir.md), [5.11](lab/days/1105.md), [W1L](lab/1104/W1L-bash-limit.md), [ST, C30, AC, RT, SC, RT2, STAC](lab/1104/ST-AC-RT-SC-blocks.md)) | TD 3/1/1/5, TU 3/0/3/4; «на вердикты не влияет» | — | без эффекта | cli 3; gate 3, work 3 |
| --hide-tools | HT | то же → [L03:1076](lab/1105/TD-TU-HT-tools-dir.md); [L10:230](lab/1110/G6-bash-count.md) | 2/2/2/4; инструменты искали в 7 из 10 сессий | **[L03:1094](lab/days/1105.md): «HT 0 — ноль по построению»**; [L10:230](lab/1110/G6-bash-count.md): G6 снят | без эффекта | cli 4; work 9, gate 2, tools 2 |
| --given-code | GC-1…6, GC25 | [L03:1099–1104](lab/1105/GC-1-given-code.md) (c927867) → L03:1106–1240 ([GC-1](lab/1105/GC-1-given-code.md), [GC-2](lab/1105/GC-2-over-generate.md), [GC-3](lab/1105/GC-3-judge-no-effect.md), [GC-4](lab/1105/GC-4-k6-all.md)), [1440–1447](lab/1105/GC25-given-code-25.md) | GC25 3/0/1/6 против W1 2/2/1/5; GC (3 bash) — лучшая из 6 даёт V на 4 из 10 | **[L03:1381–1383](lab/days/1105.md): «клетка»; вывод GC-2/4 «получен на клетке»** | без эффекта как добавка | cli 2; inputs 3, ask 1 |
| --given-files | GF | [L03:1305–1309](lab/1105/GF-given-files.md) (a792d17) → [L03:1386–1393](lab/1105/GF-given-files.md) | 01 B3x3 \| B3x3; 02 V0 \| V1; 05 P3 \| P1; 06 V5P1 \| V5B1; «в основную линию не идёт» | [L03:1381](lab/days/1105.md): абляция-«клетка» | без эффекта | cli 3; inputs 2 |
| --navigator | NV, SNV | [L03:1330–1341](lab/1105/NV-navigator.md) (8c01cde) → [L03:1420–1439](lab/1105/NV-navigator.md), [2027](lab/1105/SW1-SNV-symptom-only.md) | NV 3/0/1/6 против W1 2/2/1/5; SNV 1/0/1/8 против SW1 0/0/0/10 | [L03:2029–2030](lab/1105/SW1-SNV-symptom-only.md): калибровка смешана со входом | без эффекта (сдвинулось только чтение) | cli 2; NAV_EXAMPLE |
| --nav-v | NV2 | [L03:1559](lab/1105/IO-AQ-NV2-TP-BR.md) (d0ff3d9) → [L03:1828](lab/1105/IO-AQ-NV2-TP-BR.md), [1837](lab/1105/IO-AQ-NV2-TP-BR.md) | 1/1/1/7 — «худший» | — | без эффекта | cli 2 |
| --intent | IN | [L03:1403–1412](lab/1105/IN-intent.md) (7026793) → [L03:1448–1459](lab/1105/IN-intent.md) | 1/0/3/6 (+2 без правок) против AC 2/1/4/3; «обязательность мешает» | — | без эффекта (хуже) | cli 4; schema 1, tools 2; intent_report |
| --intent-opt | IO | [L03:1557](lab/1105/IO-AQ-NV2-TP-BR.md) → [L03:1565](lab/1105/IO-AQ-NV2-TP-BR.md), [1828](lab/1105/IO-AQ-NV2-TP-BR.md) | 3/0/1/6; поля не заполнены ни разу | **[L03:1565](lab/1105/IO-AQ-NV2-TP-BR.md): «IO на деле равно AC»** — механизм не включился | не замерен по сути | cli 5; tools 1, schema 1 |
| --ask-changed | AQ | [L03:1558](lab/1105/IO-AQ-NV2-TP-BR.md) → [L03:1828–1836](lab/1105/IO-AQ-NV2-TP-BR.md) | 2/3/2/3; на вопрос разобрались 3 из 6, сужения нет | — | без эффекта | cli 3; tools 1; gate.ask_changed |
| --plan-line | TP | [L03:1560](lab/1105/IO-AQ-NV2-TP-BR.md) → [L03:1828](lab/1105/IO-AQ-NV2-TP-BR.md), [1838](lab/1105/IO-AQ-NV2-TP-BR.md) | 1/1/3/5; правки шире | — | без эффекта | cli 2 |
| --broad-example | BR | [L03:1561](lab/1105/IO-AQ-NV2-TP-BR.md) → [L03:1828](lab/1105/IO-AQ-NV2-TP-BR.md), [1839](lab/1105/IO-AQ-NV2-TP-BR.md) | 1/0/1/8; на 00 сломал всё | — | без эффекта | cli 2 |
| --ticket-cover | TKC | [L03:2115–2133](lab/1106/TKC-TKR-cover.md) (e697afa) → [L03:2310–2330](lab/1106/TKC-TKR-cover.md) | 1/2/0/7 против TKS 2/2/0/6; «покрытие не читается» (0 ссылок из 10) | [L03:2212](lab/1106/TKC-TKR-cover.md): счётчик исправлен посреди серии (00–01 старые числа, 02–09 новые); **[L03:2290](lab/1106/TKC-TKR-cover.md) «конфаунд моего изготовления»**; [L03:2289](lab/1106/TKC-TKR-cover.md): с покрытием прочитано хуже | испорчен частично | cli 4; gate 1; _cover_lines 24 стр. |
| --ticket-ret | TKR | [L03:2210](lab/1106/TKC-TKR-cover.md) (19bd077) → [L03:2354](lab/1106/TKC-TKR-cover.md) | 1/1/0/8 | — | без эффекта | cli 3; gate 1 |
| --ticket-first | TKF | [L03:2241–2245](lab/1106/TKF-ticket-first.md) (f222d5f) → L03:2415–2423 ([TKL](lab/1106/TKL-ticket-line.md), [TKF](lab/1106/TKF-ticket-first.md)) | 1/1/2/6; «не помог чтению» | — | без эффекта | cli 3; gate 1 |
| --ticket-passed | TKP | [L03:2574–2589](lab/1106/TKP-passed.md) (bd4c669) → [L03:2846–2860](lab/1106/TKP-passed.md) | за 3 seed 3/4/4/19 против TKW 5/4/4/17; 0 улучшений в парах | [L03:2584](lab/1106/TKP-passed.md) «мой промах»; **[L03:2791–2795](lab/1106/TKP-passed.md) «мой брак» `__shape2__`, «конфаунд моего изготовления»**; [L03:2860](lab/1106/TKP-passed.md) «в базу дальше не беру»; [L03:2862](lab/1106/TKP-passed.md) автор: «не общо» | замер испорчен | cli 3; gate 2 + _cond_probes, _fired_fact, passed_fact ≈73 стр.; `__shape2__` в gate.py:617 и rerun.py:274 |
| --ticket-anchor | TKA | [L03:2746–2755](lab/1106/TKA-anchor.md) (363985f) → [L03:2841](lab/1106/TKD-why-no-key.md) | **не запускалась: «снята из очереди, ни одна не стартовала»** | [L03:2837](lab/1106/TKW-why.md), [2840](lab/1106/TKA-anchor.md): содержимое словаря убрано как подгонка; «мой промах в рекомендации» | не замерен | cli 3; gate 1 (gate.py:416); поле `line` в rerun.py |
| --resume, --resume-turn, --resume-bash | 08_IO_R, PKR | [L03:1890–1898](lab/1106/08_IO_R-resume.md) (b4e50d1) → [L03:1988–2005](lab/1106/08_IO_R-resume.md); L09:157–180 ([PKR](lab/1109/PKR-resume-bash.md), [9.11](lab/days/1109.md)) | 08_IO_R: впервые живая правка на 08 (B); PKR 6/4/8/12 против PK 5/2/7/16, keep Failed доведён до Ok в 0 из 5 | **[L09:171](lab/1109/PKR-resume-bash.md): «запас bash и другая выборка не разделены»** | инструмент стенда, замер смешан | cli 3+3+2; resume.py 73 стр. |

### Что включает `--clean`

| что делает | где в коде | чем обосновано |
|---|---|---|
| включает `check_auto_only`: одна строка «Checks run by themselves…» вместо «run smoke and rerun» плюс «they are run by themselves» | cli.py:241, 160–163; prompt.py:120–124 | CL: двойная проверка съедала ~⅓ бюджета ([L03:2899](lab/days/1106.md) — ручной rerun 15 %, smoke 7 %, чтение tests/ 14 %). Итог CL: процесс **не сдвинулся** ([L03:3223](lab/1106/CL-check-auto-only.md)), строка оставлена «как исправление изъяна» ([L03:3224](lab/1106/CL-check-auto-only.md)) |
| строка лимита: «for a few turns» → «FINAL_TURNS turns remain without bash: edits are still applied and checked» | cli.py:190–192; prompt.py:100–101 | «for a few turns без числа» ([L03:2965](lab/days/1106.md)); пункт (а) ([L03:2969](lab/days/1106.md)) |
| заметка о конце bash стала фактом: «Edits are still applied and checked…; N turns remain» | phase.py:12–13 | «Конец bash настроен на мир без авто-проверки»: bash после конца пробовали в 78 из 129 сессий ([L03:2947–2951](lab/days/1106.md), [2890](lab/days/1106.md)). **В PL отказов bash после конца стало 31 против 21: «заметка-факт… не удерживает» ([L03:3268](lab/1106/PL-plain-clean.md))** |
| отказ bash без «Use edit, then call finish» | tools.py:25–26 | то же ([L03:2969](lab/days/1106.md)) |
| «Call finish when you are done» убрано из How to work и из первого сообщения | cli.py:191–194 | «Готово» не определено: фраза встречалась трижды; Ok по тикету → finish в 61 % ([L03:2893–2897](lab/days/1106.md), [2963](lab/days/1106.md)) |
| ответ на повтор той же команды: «already run… tells you nothing new: change the command…» и прежний вывод целиком | tools.py:47–51 | [L03:3038–3041](lab/1106/PL-plain-clean.md) (первый вариант — просто вывод); [L03:3110](lab/1106/PL-plain-clean.md) «был ошибкой» → 768f357. Офлайн-проба rp: exact 0,27 у clean против 0,35 у old, «слабый плюс… ответ clean остаётся в PL» ([L03:3355](lab/1106/RP-repeat-answer.md), [3370–3372](lab/1106/RP-repeat-answer.md)); в PL повторов 1 против 7 ([L03:3269](lab/1106/PL-plain-clean.md)) |
| **10.11:** из промпта убрана фраза «README.md and the comments… describe how the parts fit together» | cli.py:195–197, коммит c918594 | «README и комментарии узлов врут» ([L03:2954–2959](lab/days/1106.md)), голые виды ([L03:2994](lab/1106/PL-plain-clean.md)). В таблице [L10:11–20](lab/1110/TY-typed-hooks.md) отдельной строкой не записано; полной серией не замерено (TY отложена, [L10:79](lab/days/1110.md)) |
| несовместим с --rerun-tool, --checked, --stages, --finish-review, --goal-k | cli.py:238–240 | — |

Оговорка из [L03:3032](lab/1106/PL-plain-clean.md): собраны исправления известных изъянов, «без новых гипотез». Пачка целиком замерена один раз (PL) и дала шум против TKD.

## 2. Стендовые скрипты

| скрипт | что делает (по docstring) | откуда (журнал, коммит) | после 9.11 |
|---|---|---|---|
| editor/check.py | цел ли харнесс в work/<tag>/src (pytest) | EJ:17, 245 (30.10, ff33255); [L03:26](lab/days/1103.md) — от него остался зависший pytest | нет |
| editor/edit_stats.py | статистика правщика по дереву (сработали ли новые сообщения) | NIGHT-1101:110 (3.11, 91b73a8); мерка P1 в [L03:56](lab/1103/P1-cite.md) | нет |
| editor/editor.py | старая обёртка запуска (B1/E); её зовут editor/launch.sh и editor/queue.sh | EJ:28 (30.10) | нет; очередь зовёт `python3 -m nrhsi.editor` (runs/q1/qj.sh:9) |
| editor/fork.py | развилка записанной сессии на ходе T, ответ N раз | [L10:80](lab/days/1110.md) (10.11, 7f21310) | **живой**: L10 H1/H2, T1, C1, T2, F1; его импортирует roll.py:24 |
| editor/merge3.py | 3-way merge src/ без модели | P4, [L03:314](lab/1103/P4-merge.md) (3.11, 67a0bf0) | нет (упомянут в help cli.py:19) |
| editor/pairs_tk.py | без docstring: пары по месту расхождения; вердикты и абсолютный путь вшиты в код | [L03:2806](lab/days/1106.md) (6.11, 073d6c0); REPORT-1106:398 | нет |
| editor/plain_inputs.py | входы v2 → входы на голых видах | [L03:3001](lab/1106/PL-plain-clean.md) (6.11, e39a5e1) | нет (typed_1110 собран tools/port_typed_1110.py) |
| editor/repeat_probe.py | офлайн-проба ответа на повтор команды | [L03:3125](lab/1106/RP-repeat-answer.md) (6–7.11, 5a4dcd2…ab4246d) | нет |
| editor/rerun.py | повтор записанных прогонов на src, первое расхождение | [L03:500](lab/1104/W-writer-variants.md) (3.11, e589703) | **живой**: gate.py:80 (RERUN_CORE), val_edit.py:41, wv_read.py:68; [L09:203](lab/1109/MP-manual-additions.md), [L10:40](lab/1110/TY-typed-hooks.md), [805](lab/1110/AA-ticket-all-any.md) |
| editor/rerun_writer.py | то же; копия для писателя | [L03:2387](lab/1106/TKV-values.md) (6.11, b1242b2) | **живой**: work.py:220 → tests/rerun_core.py |
| editor/roll.py | прокат развилки настоящим харнессом | [L10:111](lab/1110/G1-goal-line.md) (10.11, 7f21310, 3c1cdb8) | **живой**: G1, G3–G5, G7–G9, F2 |
| editor/show.py | сжатый транскрипт сессии | EJ:20 (30.10) | нет |
| editor/table.py | таблица механики сессий B1 | EJ:20 (30.10) | нет |
| editor/unchecked.py | сколько правок не проверено smoke | P3, [L03:276](lab/1103/P3-checked.md) (3.11, c0775da) | нет |
| editor/val_edit.py | замер правки на val, живьём только задетые задачи | [L09:18](lab/1109/VAL-V.md), [33](lab/1109/VAL-V.md) (9.11, 0ea5535) | да, 9.11: qj.sh `ve`/`vt`/`vet`; хвост VAL-V снят ([L09:127](lab/days/1109.md)) |
| editor/wb_stats.py | процесс сессий стенда wbench | [L03:61](lab/1103/P1-cite.md), [131](lab/1103/P2-import-src.md) (3.11, 7a6f00d) | нет |
| editor/wv_read.py | сводка runs/wvar_1104 и rerun итогового src | 4.11 (c265677); **по имени в docs не упомянут** | нет |
| tools/make_start.py | стартовый src = шаблон + патч + файлы бенча | NIGHT-1031:428 (31.10) | **живой**: nrhsi/tree.py:28, port_typed_1110.py |
| tools/port_typed_1110.py | перенос plain_1106 → typed_1110 | [L10:42](lab/1110/TY-typed-hooks.md) (10.11, 9b892cd) | одноразовый |
| tools/to_events.py | логи → поток событий | NIGHT-1101:82, [L03:410](lab/days/1103.md) (30.10) | нет |

В `editor/` кроме скриптов лежат ~100 файлов `logs_*.out`, `launch.sh` и `queue.sh` от прогонов B1/E/r1/r2 (29–30.10).

**Чем отличаются `editor/rerun.py` и `editor/rerun_writer.py`.**
- **`rerun.py` (534 стр.)** — рабочий инструмент механики. Его подпроцессом вызывает `gate._replay` для проверки по тикету (`--json --cover --watch`; gate.py:210–212). При `--rerun-tool` его же вызывает `rerun_output`. Кроме того, его зовут val_edit.py, wv_read.py и ручные пробы. Только в нём есть `--watch`, `__shape__`/`__shape2__`, `__ret__`/`__val__` и поле `line`; справка по-русски.
- **`rerun_writer.py` (505 стр.)** — копия `rerun.py` на 19bd077, сделанная 6.11 (b1242b2). `work.py:220` пропускает её через `plain.strip` и кладёт в копию писателя как `tests/rerun_core.py`. Это ядро `tests/rerun.py`, который писатель запускает сам, и его же вызывает авто-проверка (`gate.rerun_output` → `WK.tool_run(run,"rerun")`). `--watch` в ней нет, справка английская.
- **Расхождение.** [L03:2387](lab/1106/TKV-values.md) и [L03:2566](lab/1106/TKW-why.md), а также комментарий work.py:217 говорят «заморожена на 19bd077». На деле файл правился 10.11 в c918594 и 9b892cd. А `rerun.py` разошёлся с 19bd077 на 48+/6− строк. Получается, что в одном ответе на правку вывод rerun идёт из одного ядра, а строка тикета — из другого. Это близко к замечанию [L10:84](lab/1110/TY-typed-hooks.md) о разных Python.

## 3. Карта docs/*.md

| файл | период записей (создан → последняя правка) | компонент | runs/… чаще всего | коммиты (сколько, даты) | главный вывод, как в документе |
|---|---|---|---|---|---|
| AGREE-1105 | 5.11 (b7d4501) | писатель (24 сессии) и судья (10) | wvar_1104×2, thin-runs | — | AGREE:61–72: у писателя основной источник согласия — наблюдение (12), у судьи — запись прогона (6); «согласие не пропадает, меняется источник» |
| AUDIT-1031 | 31.10 | исследователь, редактор, проверяльщик | — | — | AUDIT:5–8: нет границы промпт/эпизод; «писатель не видел ни одного настоящего ответа среды» |
| BACKLOG | 29.10 | исследователь (grep по jsonl, runs) | — | — | два отложенных пункта |
| DIARY-1029 | 29.10 (написан 6.11 22:36) | исследователь (A1/A3/A7), редактор B1, R2 | — | 1, 29.10 | наблюдения ≈ варианты (14–19 %), варианты ломают чаще → выбраны наблюдения |
| DIARY-1030 | 30.10 | редактор, R2, стенд | view_v3 | 9, 30.10 | smoke был тестом с наводкой; правки 9B без прироста (25/40 против 27/40, 2/20 против 4/20) |
| DIARY-1031 | 31.10 | круги ревьювер → писатель, репо | — | 6, 31.10 | App 3/20 против 1/20; писатель повторяет «детектор → break» |
| DIARY-1101 | 1.11 | дерево | — | 2, 1.11 | три узла App 0/30: харнесс сломан правками |
| DIARY-1102 | 2.11 | дерево, разметка правок | — | 2, 2.11 | ALF: большая часть правок мёртвая |
| DIARY-1103 | 3.11 | писатель | q1 | — | val не подтвердил прирост дерева; `--cite`/`--import-src`/`--smoke-calls`/`--checked` «поведения почти не меняют» |
| DIARY-1104 | 4.11 | писатель (варианты W) | wvar_1104 | — | 7 вариантов не различаются (1–2 V из 10) |
| DIARY-1105 | 5.11 | писатель, судья v2, GC | val_1102 | 2 (0332e9e — ветка thin, d0ff3d9) | лучшая из 6 — V на 4 из 10; выбор судьёй ненадёжен |
| DIARY-1106 | 6.11 (написан 22:18, **до итогов CL/PL/NT**) | писатель, TK* | — | — | механизмы TK* почти не меняют вердикты (35 из 38); TKK — намёк |
| IDEAS-1031 | 31.10 | ревьювер | — | — | IDEAS:6–8: «решает одно: проверено ли утверждение счётом… или исполнением кода» |
| LAB-1103 | 3.11 00:37 → 7.11 16:59 (169 правок) | писатель (основное); ревьювер P5, судья, комбинатор, проба повтора | wvar_1104×19, manual_1103×7, q1×5, ask_1106×5 | 30 хэшей, 3.11–7.11 (5 из них на ветке thin-writer) | [L03:534–535](lab/1104/W-writer-variants.md): «варианты между собой не различаются»; [L03:2828](lab/days/1106.md): механизмы меняют ход сессии, но не вердикт; [L03:3272](lab/1106/PL-plain-clean.md): чистая база «не хуже и не лучше» |
| LAB-1109 | 9.11 01:15 → 10.11 00:55 | писатель + замер на val | tree_alf_1101×8, wvar_1104 | 6d529ba; 2df6cff — sha профиля стенда, d976b57 — коммит репо llm | [L09:95](lab/1109/VAL-V.md): 06 даёт +8 на ALF val; [L09:155](lab/1109/PK-keep-plain.md): TKK на чистой базе не повторился; [L09:179](lab/1109/PKR-resume-bash.md): запас bash keep не чинит; [L09:277](lab/1109/MP3-thinking.md): thinking не поднял долю годных |
| LAB-1110 | 10.11 ~00:55 → 17:34 | писатель: типы, ручной стенд, thinking, условие для 9B | typed_1110×4, view_v3×3, scratchpad fk/ | 7, 10.11 00:33–01:56 (c2e612a не упомянут) | [L10:641–642](lab/1110/G9-all-together.md): с условием во входе и рассуждением точно 5 из 10, тикет пройден в 8 из 10; «узкое место уходит к наблюдению» |
| NIGHT-1029 | 29.10 (в git с 31.10) | исследователь, редактор B1 | — | — | таблица фаз: free evidence, obs вместо fix |
| NIGHT-1030 | 30.10 | редактор, R2, стенд (view_b2) | view_v2 | — | NIGHT-1030:36: «ни одна правка 9B не дала прироста на свежих задачах» |
| NIGHT-1031 | 30→31.10 | стенд (бенч = оригинал), круги ревьювер/писатель | view_v3×10 | 8, 30–31.10 (3 хэша не из этого репо) | база ALF 24/40, App 1/20 (:41–46); вывод по трём кругам App (:194) |
| NIGHT-1101 | 31.10 → 3.11 | ревьювер (лестница), репо, дерево | wbench_1103, val_1102, tree_* | 5, 31.10–2.11 | :46 «отбивка меняет время report, но не точность»; :99 правки ALF мёртвые |
| ORCHESTRATOR-PROMPT | 6.11 | метод (промпт оркестратора) | q1 | — | промпт выведен из выборов автора |
| PROGRESS-0903-1106 | 3.09–6.11 (написан 7.11) | диплом целиком | — | 51, 22.09–6.11 (21 не из этого репо) | :83 «после 03.11 уровня 3 нет» |
| READ-writer-1103 | 3.11 | писатель (P1–P3, P6, P4) | — | — | :32–33: промпт по наблюдению верен почти всегда, код мёртв или ломает |
| REFLECT-INSIDE-1106 | 6.11 | автор и метод | — | — | :140: «Цель метода выше прироста…» |
| REPORT-1106 | 5.11 22:53 → 6.11 23:39 | писатель, TK*, CL, PL | — | 2 (69e3d91, 74e8460) | :7 «ни одна проба не подняла число верных правок сверх шума» |
| TRACE-VIEWS | 30.10 | стенд (трассы) | view_v2 | — | три варианта представления трасс, решение не принято |

## 4. Ветки git

| ветка | впереди develop | позади develop | последний коммит | 3 последних сообщения | упоминания в журналах |
|---|---|---|---|---|---|
| feature/thin-writer (только локально, worktree nrhsi-wt/thin) | 18 | 198 (развилка 21f66dc, 4.11) | 45ae4a6, 6.11 23:41 | judge2 --rev; judge2 --bare; judge2 --three | [L03:910](lab/1104/THIN-thin-writer.md), [930](lab/1104/THIN-thin-writer.md), [1039](lab/1105/JV2-reading-judge.md), [3306](lab/1106/JGP-judge-polarity.md); DIARY-1105:3, 15. В ветке флаги писателя `--replay`, `--contrast`, `--contrast-judge`, `--triz` и judge2 — в develop их нет |
| feature/verifier-r2 (= origin; worktree в /private/tmp, prunable) | 9 | 364 (развилка dba5860, 30.10) | 3281850, 30.10 15:37 | заметки после ревью; исправлен неверный факт; критерий фильтра (>90 % / >0), v3 b10 проходит | NIGHT-1030:3, 29; [L03:920](lab/1104/THIN-thin-writer.md); DIARY-1030 («R2 закрыт») |
| origin/upstreams-submodules | 0 | 374 | 2452c63, 29.09 02:05 | queue.json…; setup_envs…; раннеры записей… | не найдено |
| master (= origin/master) | 0 | 362 (предок develop) | 229cead, 30.10 17:13 | адрес модели — шлюз :8090; хуки-пустышки; which в песочнице | NIGHT-1101:67; DIARY-1031:10, 65; ORCHESTRATOR:83; [L03:1810](lab/days/1106.md), [2198](lab/days/1106.md) («merge в master — не без автора») |

Кроме того, develop опережает origin/develop на 40 коммитов: всё 10.11, от 7a158ce до c2e612a, не запушено.

## Самые явные расхождения

1. **`--ticket-passed` (TKP).** Замер испорчен (`__shape2__`, [L03:2791–2795](lab/1106/TKP-passed.md)), в базу не взят ([L03:2860](lab/1106/TKP-passed.md)), автор: «не общо» ([L03:2862](lab/1106/TKP-passed.md)). Код остался: ≈73 строки gate.py:462–538 и `__shape2__` в gate.py:617 и editor/rerun.py:274.
2. **`--ticket-anchor` (TKA).** Не запускалась ни одна сессия ([L03:2841](lab/1106/TKD-why-no-key.md)), но флаг, gate.py:416 и поле `line` в rerun.py на месте. Рядом осталась `hide = frozenset()` (gate.py:619) — след убранного правила «нет ключа», которое названо подгонкой ([L03:2837](lab/1106/TKW-why.md)).
3. **«Заморозка» rerun_writer.py.** Журнал ([L03:2387](lab/1106/TKV-values.md), [2566](lab/1106/TKW-why.md)) и комментарий work.py:217 говорят «= rerun.py на 19bd077», но файл правили 10.11 (c918594, 9b892cd). Авто-проверка и проверка по тикету в одном ответе идут через два разных ядра повтора.
4. **База 10.11 изменена без серии.** c918594 и 5059a5d поменяли `--clean` (убрана фраза о комментариях), строки Failed/keep, сводку rerun и `--at` в README. e25f33f/f154d23 добавили типы хуков и `tests/runs.py`. Серия TY отложена ([L10:79](lab/days/1110.md)), «ни одной живой сессии на типах» ([L10:56](lab/1110/TY-typed-hooks.md)). Проверка только развилками на одном входе 08, так что PK/PL 5/2/7/16 и 4/2/8/16 с нынешней базой несравнимы. c2e612a: «Не замерено» ([L10:814](lab/1110/AA-ticket-all-any.md)).
5. **`--rerun-at`.** W14 «не принят» ([L03:2953](lab/days/1106.md)), но `--at` с 10.11 в README всегда ([L10:19](lab/1110/TY-typed-hooks.md)), без замера. Сам флаг остался, C.RERUN_AT только присваивается и нигде не читается.
6. **`--intent-opt`.** «IO на деле равно AC» ([L03:1565](lab/1105/IO-AQ-NV2-TP-BR.md)) — механизм не включился, код в tools/schema остался. То же по сути с `--import-src` (исход по построению, [L03:1090](lab/days/1105.md)) и метриками `--checked`/`--hide-tools` («ноль по построению», [L03:1091](lab/days/1105.md), [1094–1095](lab/days/1105.md)).
7. **`--stages`.** Первые сессии испорчены ([L03:897–899](lab/1104/ST-AC-RT-SC-blocks.md)), итог V4 = V4 против C30 ([L03:937](lab/1104/ST-AC-RT-SC-blocks.md)). 8 строк в phase/tools/state и STAGES_LINE остались; [L10:238](lab/1110/G6-bash-count.md) предлагает вернуться к флагу, не сделано.
8. **`--ticket-cover`.** «Покрытие не читается» (0 из 10, [L03:2323](lab/1106/TKC-TKR-cover.md)), счётчик правился посреди серии ([L03:2212](lab/1106/TKC-TKR-cover.md)), есть конфаунд с rerun_core ([L03:2290](lab/1106/TKC-TKR-cover.md)). Флаг и `_cover_lines` остались.
9. **Обоснование `--clean` слабее, чем его состав.** Заметка о конце bash в PL отказы не уменьшила, а увеличила (31 против 21, [L03:3268](lab/1106/PL-plain-clean.md)). CL процесс не сдвинула ([L03:3223](lab/1106/CL-check-auto-only.md)). Обе части остаются в базе как «исправление изъяна».
10. **Тикеты с keep в базе.** Базовые серии идут на `tickets_1106k` ([L10:63](lab/1110/TY-typed-hooks.md)), хотя TKK 8/3/5/14 на чистой базе не повторился: PK 5/2/7/16 ≈ PL ([L09:155](lab/1109/PK-keep-plain.md)), а запас bash keep Failed не чинит (0 из 5, [L09:173](lab/1109/PKR-resume-bash.md)).

Не найдено: упоминаний `wv_read.py` по имени в журналах; ветки upstreams-submodules в журналах.
