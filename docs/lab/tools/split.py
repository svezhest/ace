#!/usr/bin/env python3
"""Разбиение журналов LAB-1103, LAB-1109, LAB-1110 (по 728e61b) на файлы проб и хронологию дней.

Строки журналов переносятся как есть, целыми диапазонами (раскладка — SPEC ниже). Новый текст —
только заголовки файлов, связки «Из записи …», отметки пропусков и указатели в хронологии дней.
Листинги кода («**Код пробы**», «**Код и запуск**») уходят в конец файла пробы.
Над каждым перенесённым куском — комментарий <!-- LAB-1103.md:51–71 --> со строками старого файла.

Запуск из корня репозитория: python3 docs/lab/tools/split.py
Проверка переноса: python3 docs/lab/tools/check.py
"""
import os
import re
import subprocess

BASE = '728e61b'
SRC = {'L03': 'docs/LAB-1103.md', 'L09': 'docs/LAB-1109.md', 'L10': 'docs/LAB-1110.md'}
OUT = 'docs/lab'

DAYS = {
    'd1103': ('days/1103.md', '3.11'), 'd1104': ('days/1104.md', '4.11'), 'd1105': ('days/1105.md', '5.11'),
    'd1106': ('days/1106.md', '6.11'), 'd1107': ('days/1107.md', '7.11'), 'd1109': ('days/1109.md', '9.11'),
    'd1110': ('days/1110.md', '10.11'),
}
# день записи — по строке старого файла
DAYRANGE = {
    'L03': [(1, 508, 'd1103'), (509, 922, 'd1104'), (923, 1688, 'd1105'), (1689, 3314, 'd1106'), (3315, 10**6, 'd1107')],
    'L09': [(1, 260, 'd1109'), (261, 10**6, 'd1110')],
    'L10': [(1, 10**6, 'd1110')],
}

# ключ → (файл, идентификатор, заголовок файла)
P = {}
def probe(key, path, ident, title):
    P[key] = (path, ident, title)

probe('VAL1', '1103/VAL1-tree-node-val.md', '§1 Val', 'Val: лучший узел дерева против корня')
probe('P0', '1103/P0-noise.md', 'P0', 'шумовой порог (App)')
probe('P1', '1103/P1-cite.md', 'P1', 'писатель видит процитированные строки (`--cite`)')
probe('P2', '1103/P2-import-src.md', 'P2', 'python3 с импортом src у писателя (`--import-src`)')
probe('P6', '1103/P6-smoke-calls.md', 'P6', 'smoke показывает вызовы (`--smoke-calls`)')
probe('P3', '1103/P3-checked.md', 'P3', 'правка без проверки не применяется (`--checked`)')
probe('P4', '1103/P4-merge.md', 'P4', 'комбинатор на 9B (`--arm merge`)')
probe('P5', '1103/P5-reviewer-check.md', 'P5', 'ревьювер: находка = команда проверки (`EVIDENCE_MODE=check`)')
probe('P7', '1103/P7-ideal-input.md', 'P7', 'идеальный вход писателю')
probe('P7b', '1103/P7b-ideal-no-new.md', 'P7b', 'идеальный вход без блока `new`')
probe('S12', '1103/S12-manual-inputs.md', '§12–13', 'ручные входы писателю')
probe('W', '1104/W-writer-variants.md', 'W0–W17', 'rerun и варианты писателя на 10 наблюдениях (W0, W1, W2, W10, W14, W15, W17; формы (а)/(б))')
probe('W1L', '1104/W1L-bash-limit.md', 'W1L', 'абляция лимита bash (02/06 и 00/08 — «набор скрыто недостаточен?»)')
probe('BLK', '1104/ST-AC-RT-SC-blocks.md', 'ST, C30, AC, RT, SC, RT2, STAC', 'блоки 1–2: этапы против C30; авто-проверка, rerun-инструмент, scratch')
probe('THIN', '1104/THIN-thin-writer.md', 'тонкий писатель', '«тонкий писатель» на 01 и 05 (агент, ветка feature/thin-writer)')
probe('M01', '1105/01m-input-wording.md', '01m', 'изменённый вход 01m')
probe('TD', '1105/TD-TU-HT-tools-dir.md', 'TD, TU, HT', 'каталог инструментов (`--tools-dir`, `--hide-tools`)')
probe('JV2', '1105/JV2-reading-judge.md', 'судья v2', 'читающий судья v2')
probe('GC1', '1105/GC-1-given-code.md', 'GC-1', 'писатель без обзора (`--given-code`)')
probe('GC2', '1105/GC-2-over-generate.md', 'GC-2', 'over-generate K=6 на 02 и 06')
probe('GC3', '1105/GC-3-judge-no-effect.md', 'GC-3', 'судья с третьим значением «no effect»')
probe('GC4', '1105/GC-4-k6-all.md', 'GC-4', 'K=6 на всех 10')
probe('GC5', '1105/GC-5-judge-bare.md', 'GC-5', 'судья видит код без комментариев (`--bare`)')
probe('GC6', '1105/GC-6-judge-retest.md', 'GC-6', 'судья: повтор с другими seed')
probe('AGREE', '1105/AGREE-agreement.md', 'согласие', 'разбор «согласия»')
probe('GF', '1105/GF-given-files.md', 'GF', 'абляция «все файлы в первом сообщении» (`--given-files`)')
probe('NV', '1105/NV-navigator.md', 'NV', 'точный навигатор, ступень 1 (`--navigator`)')
probe('GC25', '1105/GC25-given-code-25.md', 'GC25', 'W1 + `--given-code` при 25 bash')
probe('IN', '1105/IN-intent.md', 'IN', 'намерение в edit (`--intent`)')
probe('B5', '1105/IO-AQ-NV2-TP-BR.md', 'IO, AQ, NV2, TP, BR', 'блок «всё, что можно»')
probe('SW', '1105/SW1-SNV-symptom-only.md', 'SW1, SNV', 'входы «только симптом»')
probe('B1', '1106/b1-ask-manual.md', 'b1', 'ручной режим `ask.py`, батарея b1')
probe('B2', '1106/b2-self-critique.md', 'b2', 'самокритика и «сначала верный прогон»')
probe('B3', '1106/b3-question-forms.md', 'b3', 'формы вопроса и атрибуция')
probe('B4', '1106/b4-choice-swapped.md', 'b4', 'choice с переставленными вариантами')
probe('R08', '1106/08_IO_R-resume.md', '08_IO_R', 'воскрешение 08_IO (`--resume`)')
probe('TK', '1106/TK-TKS-ticket.md', 'TK, TKS', 'ожидание ревьювера в тикете: скрыто (`--ticket`) и видно (`--ticket-show`)')
probe('TKC', '1106/TKC-TKR-cover.md', 'TKC, TKR', 'покрытие изменённых строк (`--ticket-cover`) и что вернули `return` (`--ticket-ret`)')
probe('TKF', '1106/TKF-ticket-first.md', 'TKF', 'проверка по тикету — первой (`--ticket-first`)')
probe('TKL', '1106/TKL-ticket-line.md', 'TKL', 'факт покрытия одной фразой в строке Failed (`--ticket-line`)')
probe('TKV', '1106/TKV-values.md', 'TKV', 'значения операндов (`--ticket-values`); TKS/TKV на трёх seed')
probe('TKVB', '1106/TKVB-bash40.md', 'TKVB', 'TKV + bash 40')
probe('TKW', '1106/TKW-why.md', 'TKW', 'почему факт не действует (`--ticket-why`)')
probe('TKP', '1106/TKP-passed.md', 'TKP', 'факт о задетом удачном прогоне (`--ticket-passed`)')
probe('TKA', '1106/TKA-anchor.md', 'TKA', 'якорь на лог и содержимое словаря (`--ticket-anchor`)')
probe('TKD', '1106/TKD-why-no-key.md', 'TKD', 'TKW без правила «нет ключа»')
probe('TKK', '1106/TKK-keep.md', 'TKK', 'keep в тикете')
probe('CL', '1106/CL-check-auto-only.md', 'CL', 'строка проверки без двойной инструкции (`--check-auto-only`)')
probe('PL', '1106/PL-plain-clean.md', 'PL', 'голые виды + `--clean`')
probe('RP', '1106/RP-repeat-answer.md', 'rp_1106…', 'ответ на повтор команды без сессий (rp_1106 и следующие)')
probe('SEL', '1106/SEL-gc-pool-select.md', 'отбор прибором', 'отбор из пула GC прибором (тикет + keep)')
probe('NT', '1106/NT-no-trust.md', 'NT', 'PL без «trust your colleague initially» (`--no-trust`)')
probe('JGP', '1106/JGP-judge-polarity.md', 'jgp', 'полярность вопроса судьи (`--rev`)')
probe('VALV', '1109/VAL-V.md', 'VAL-V', 'двигают ли правки с вердиктом V задачи val')
probe('PK', '1109/PK-keep-plain.md', 'PK', 'PL + keep')
probe('PKR', '1109/PKR-resume-bash.md', 'PKR', 'те же сессии PK, +15 bash после конца бюджета')
probe('MP', '1109/MP-manual-additions.md', 'MP', 'три добавки ко входу в ручном режиме')
probe('MP2', '1109/MP2-check-own-condition.md', 'MP2', 'проверка своего условия на последовательности из наблюдения')
probe('MP3', '1109/MP3-thinking.md', 'MP3', 'те же вопросы MP с thinking')
probe('TY', '1110/TY-typed-hooks.md', 'TY', 'типизированный интерфейс хуков и серия TY')
probe('G1', '1110/G1-goal-line.md', 'G1', 'цель в промпте против мерки')
probe('G2', '1110/G2-failed-wording.md', 'G2', 'читается ли Failed по тикету как провал')
probe('G3', '1110/G3-full-sessions.md', 'G3', 'десять полных сессий на 08 после замены строки')
probe('G4', '1110/G4-tail-10.md', 'G4', 'десять ходов без bash вместо трёх')
probe('G5', '1110/G5-condition-in-input.md', 'G5', 'условие, названное во входе')
probe('G6', '1110/G6-bash-count.md', 'G6', 'подсчёт bash до первой правки; кандидат G6 (снят)')
probe('G15C', '1110/G1-G5-code.md', 'G1–G5 (код)', 'код и запуск проб G1–G5')
probe('H12', '1110/H1-H2-crash.md', 'H1, H2', 'падение кода на одном ходу; pyflakes и падение')
probe('T1', '1110/T1-thinking-fork.md', 'T1', 'thinking на ходе первой правки')
probe('C1', '1110/C1-condition-form.md', 'C1', 'форма условия и повтор наблюдения на ходе первой правки')
probe('T2', '1110/T2-thinking-condition.md', 'T2', 'thinking на развилках G5')
probe('G7', '1110/G7-thinking-session.md', 'G7', 'сессия на thinking целиком')
probe('F1', '1110/F1-one-turn-after-failed.md', 'F1', 'один ход после Failed')
probe('F2', '1110/F2-chain-after-failed.md', 'F2', 'цепочка ходов после Failed (g7_r0)')
probe('F2b', '1110/F2b-chain-g7r6.md', 'F2b', 'цепочка ходов после Failed (g7_r6)')
probe('G8', '1110/G8-thinking-tail-8.md', 'G8', 'thinking, хвост 8')
probe('G9', '1110/G9-all-together.md', 'G9', 'условие во входе + thinking + хвост 8')
probe('K1', '1110/K1-condition-one-call.md', 'K1', 'условие из наблюдения одним вызовом 9B')
probe('K1c', '1110/K1c-with-run28.md', 'K1c', 'условие одним вызовом, с шагами run 28')
probe('K2', '1110/K2-test-tool.md', 'K2', 'условие с инструментом `test`')
probe('K3', '1110/K3-test-tool-v2.md', 'K3', 'условие с инструментом `test`, вторая постановка')
probe('K4', '1110/K4-answer-tool.md', 'K4', 'условие с инструментами `test` и `answer`, входы 08 и 00')
probe('AA', '1110/AA-ticket-all-any.md', 'all/any', 'тикет: значения для `all(…)` / `any(…)`')

# раскладка: «начало-конец ключ»; диапазоны каждого файла идут подряд и покрывают его целиком
SPEC = {
'L03': """
1-27 d1103
28-40 VAL1
41-42 d1103
43-50 P0
51-122 P1
123-147 P2
148-274 P6
275-311 P3
312-391 P4
392-398 P5
399-413 d1103
414-415 P7
416-418 d1103
419-432 P7
433-434 P6
435-436 P4
437 P5
438 VAL1
439 P4
440-450 P5
451-452 d1103
453-457 P7b
458-462 P5
463-464 d1103
465-475 P7b
476-491 S12
492-494 d1103
495 S12
496-498 d1103
499-674 W
675-682 d1104
683 W1L
684-685 d1104
686-694 BLK
695-704 W1L
705-890 BLK
891-896 W1L
897-900 BLK
901-906 W1L
907-934 THIN
935-947 BLK
948-952 M01
953-1032 TD
1033-1050 JV2
1051-1052 d1105
1053-1056 BLK
1057-1062 M01
1063-1068 TD
1069 d1105
1070-1072 W1L
1073 d1105
1074-1075 BLK
1076 TD
1077-1078 d1105
1079 BLK
1080 TD
1081-1098 d1105
1099-1183 GC1
1184-1199 GC2
1200-1212 GC3
1213-1241 GC4
1242-1259 GC5
1260-1261 GC6
1262-1267 AGREE
1268-1281 GC6
1282-1299 AGREE
1300-1304 THIN
1305-1329 GF
1330-1377 NV
1378-1384 d1105
1385 GC25
1386-1394 GF
1395-1402 d1105
1403-1419 IN
1420-1439 NV
1440-1447 GC25
1448-1552 IN
1553-1665 B5
1666-1667 SW
1668 JV2
1669-1676 SW
1677-1688 d1105
1689-1781 B1
1782-1787 B2
1788-1811 d1106
1812-1840 B5
1841-1857 B3
1858-1889 d1106
1890-1959 R08
1960-1987 TK
1988-2005 R08
2006-2010 TK
2011-2033 SW
2034-2063 TK
2064-2085 B1
2086-2090 TK
2091-2114 B3
2115-2182 TKC
2183-2189 TK
2190-2200 d1106
2201-2206 TK
2207-2214 TKC
2215-2225 B3
2226-2235 B2
2236-2240 d1106
2241-2262 TKF
2263-2266 B3
2267-2270 B4
2271-2273 d1106
2274-2284 TK
2285-2294 TKC
2295-2308 B4
2309-2333 TKC
2334-2352 TKL
2353-2355 TKC
2356-2369 d1106
2370-2385 TKL
2386-2401 TKV
2402-2410 B2
2411-2417 TKL
2418-2420 TKF
2421-2422 TKL
2423-2424 TKF
2425-2432 TKL
2433-2444 TKVB
2445-2465 TKV
2466-2479 TKVB
2480-2481 TKV
2482-2490 B2
2491-2554 TKV
2555-2573 TKW
2574-2696 TKP
2697-2745 TKW
2746-2773 TKA
2774-2800 TKP
2801-2831 d1106
2832-2839 TKW
2840 TKA
2841-2845 TKD
2846-2871 TKP
2872-2904 d1106
2905-2916 TKK
2917 CL
2918-2919 TKK
2920-2941 CL
2942-2973 d1106
2974-2991 TKD
2992-3013 PL
3014-3031 d1106
3032-3043 PL
3044-3051 d1106
3052-3120 PL
3121-3154 RP
3155-3173 TKK
3174-3208 RP
3209-3225 CL
3226-3257 SEL
3258-3273 PL
3274-3303 NT
3304-3314 JGP
3315-3333 RP
3334-3347 NT
3348-3374 RP
3375-3387 JGP
3388 RP
""",
'L09': """
1-13 d1109
14-122 VALV
123-124 d1109
125-126 PK
127 d1109
128-132 PK
133-137 d1109
138-156 PK
157-163 PKR
164 d1109
165-181 PKR
182-196 d1109
197-230 MP
231-260 MP2
261-280 MP3
""",
'L10': """
1-5 d1110
6-75 TY
76-81 d1110
82-93 TY
94-131 G1
132-158 G2
159-191 G3
192-202 G4
203-214 G5
215-240 G6
241-263 G15C
264-275 G4
276-314 H12
315-332 T1
333-347 G5
348-367 C1
368-385 T1
386-400 C1
401-435 T2
436-470 G7
471-481 H12
482-520 F1
521-552 F2
553-562 F2b
563-574 F2b
575-608 G8
609-645 G9
646-678 K1
679-701 K1c
702-727 K2
728-752 K3
753-799 K4
800-822 AA
823-844 d1110
""",
}

# «Связанные записи» в конце файла пробы: (ключ файла или дня, что там)
SEE = {
    'VAL1': [('d1105', '«Замеры дерева 1–2.11 и шум»: ALF n4 и App n8 на val ещё раз, 5.11')],
    'P0': [('d1103', '«Ошибки дня, отмеченные автором» (§10): повтор n0 при T=0 — результат известен заранее'),
           ('VAL1', 'строка «Val App dev (57), T=0» (§8): итог повтора n0')],
    'P1': [('d1103', '§5 «Решения автора, 04:20»: писателя не мерить замером задач'),
           ('d1103', '§6 «Ручной разбор писателя, 05:00»: все 24 сессии obs/cite/imp/chk'),
           ('d1103', '«Ошибки дня, отмеченные автором» (§10)')],
    'P2': [('d1103', '§6 «Ручной разбор писателя, 05:00»'), ('d1103', '«Ошибки дня, отмеченные автором» (§10)'),
           ('d1105', '«Пробы с исходом по построению»: импорт src писатель делал и без флага')],
    'P6': [('d1103', '§6 «Ручной разбор писателя, 05:00»')],
    'P3': [('d1103', '§6 «Ручной разбор писателя, 05:00»'), ('BLK', 'C30 (`--bash-limit 30 --checked`) — блок 1'),
           ('d1105', '«Пробы с исходом по построению»: «правок без smoke после — 0» — ноль по построению')],
    'P4': [('VAL1', 'строка «Val App dev (57), T=0»: merge n8+n12 на val'), ('d1103', '«Ошибки дня, отмеченные автором» (§10)'),
           ('d1105', '«Пробы с исходом по построению»: 3-way merge n8+n12 на val')],
    'P7': [('d1103', '«Ошибки дня, отмеченные автором» (§10): P7 — во входах был готовый код')],
    'S12': [('d1103', '§14 «10 верных наблюдений в трёх формах, 17:20»')],
    'W': [('d1104', '§17 «Как писатель тратит bash»'),
          ('d1105', '«Пробы с исходом по построению»: W1 против W15 «парами»'),
          ('d1106', '«6.11, 17:05 — сверка промпта…»: `--at` (W14) не принят')],
    'W1L': [('d1104', '§17 «Как писатель тратит bash»'), ('d1105', '«Чтение очереди писателя, часть 2»: сводка V/P/B/x'),
            ('d1105', '«Пробы с исходом по построению»: блок 3 и абляции L не пары'),
            ('d1106', '«Бюджет bash: правила промпта или ритуал»'), ('TKVB', 'TKVB — TKV + bash 40')],
    'BLK': [('d1105', '«Чтение очереди писателя, часть 1/2»: сводка V/P/B/x по вариантам'),
            ('d1105', '«Пробы с исходом по построению»: «вслепую 0» — ноль по построению'),
            ('M01', '01m_STAC — изменённый вход на плече STAC')],
    'THIN': [],
    'M01': [('d1105', '«Чтение очереди писателя, часть 1»')],
    'TD': [('d1105', '«Чтение очереди писателя, часть 2»: сводка V/P/B/x, решение о V? на 09_TU'),
           ('d1105', '«Пробы с исходом по построению»: «читали исходник инструментов: HT 0»'),
           ('G6', 'кандидат G6 (10.11) снят по итогу этой пробы')],
    'JV2': [('d1105', '«Пробы с исходом по построению»: судья v2 «каждый вызов дал verdict»')],
    'GC1': [('d1105', '«Принцип от пользователя: опора, не клетка»: GC — клетка')],
    'GC2': [('d1105', '«Принцип от пользователя: опора, не клетка»: вывод GC-2/GC-4 получен на клетке')],
    'GC4': [('d1105', '«Принцип от пользователя: опора, не клетка»: вывод GC-2/GC-4 получен на клетке'),
            ('SEL', 'отбор из пула GC прибором, 6.11')],
    'GC6': [('JGP', 'полярность вопроса судьи — отложенное с GC-6'), ('SEL', 'отбор из пула GC прибором против судьи GC-6'),
            ('d1106', '«6.11, 18:08 — разбор «отложенного»…»: почему не сделано отложенное GC-6')],
    'AGREE': [('NT', 'писатель без «trust your colleague initially»'), ('JGP', 'полярность вопроса судьи')],
    'GF': [('d1105', '«Принцип от пользователя: опора, не клетка»: GF — клетка')],
    'NV': [('SW', 'SNV — навигатор на входах «только симптом»'), ('B5', 'NV2 — навигатор, ступень 2')],
    'B5': [('d1106', '«Где писатель ошибается на 00, 04, 08 (блок IO..BR, чтение рассуждений)» и «Поправки автора к разбору 00/04/08»'),
           ('d1106', '«План на 6.11, если автор не отвечает», п. 2'), ('d1106', '«Мерка: пары по месту расхождения»: ночной блок так не разобран')],
    'B1': [('d1106', '«План на 6.11, если автор не отвечает», п. 1'), ('d1106', '«Чтение 6.11, 06:20…», «Сводно»: отбор на модели (choice, crit) хуже механики')],
    'B2': [('B1', 'b1: crit — критика правки коллеги (на 01 crit 5/5 называет риск)')],
    'B3': [('d1106', '«Чтение 6.11, 06:20…», «Сводно»'), ('d1106', '«TKS s2 итог, TKC 00–05…»: поправка времени в заголовках 06:20 и 06:45')],
    'TK': [('d1106', '«TKR итог, TKL/TKF 00–03»: итоговые правки совпадают при разных вариантах проверки'),
           ('d1106', '«Мерка: пары по месту расхождения»: TK* по парам; конфаунд длины `rerun_core.py`'),
           ('TKV', '«TKS/TKV на трёх seed»: TKS s3 и суммы за три seed'), ('TKC', '«TKC итог…»: «Главное: покрытие не читается» (Failed замечают в TK, TKS)')],
    'TKC': [('d1106', '«Чтение 6.11, 06:20…», «Сводно»'), ('d1106', '«TKR итог, TKL/TKF 00–03»: итоговые правки совпадают; TKF и TKL 00–03'),
            ('d1106', '«Мерка: пары по месту расхождения»')],
    'TKF': [('d1106', '«Чтение 6.11, 06:20…», «Сводно»: следующая точка трения — чтение'), ('d1106', '«TKR итог, TKL/TKF 00–03»: TKF 00–03'),
            ('d1106', '«Мерка: пары по месту расхождения»: проверка первой (TKF/TKR)'), ('TKL', '«TKL и TKF итог»: общая таблица и V/P/B/x')],
    'TKL': [('d1106', '«TKR итог, TKL/TKF 00–03»: TKL 00–03 и совпадение итоговых правок'), ('d1106', '«Мерка: пары по месту расхождения»: факт в строке (TKL/TKS)')],
    'TKV': [('d1106', '«Мерка: пары по месту расхождения»')],
    'TKW': [('d1106', '«Мерка: пары по месту расхождения»'), ('TKD', 'TKD — TKW без правила ключа'), ('TKA', 'TKA — якорь, снята')],
    'TKP': [('d1106', '«Мерка: пары по месту расхождения»')],
    'TKA': [('TKD', 'строка «TKA снята из очереди… Вместо неё TKD»')],
    'TKK': [('d1106', '«Ещё три места промпта писателя»: откуда TKK и CL'), ('PK', 'PK, 9.11 — keep на чистой базе')],
    'CL': [('d1106', '«Ещё три места промпта писателя»: откуда CL'), ('TKK', 'строка «Очередь: TKK … CL …»')],
    'PL': [('d1106', '«6.11, 17:05 — сверка промпта…»: изъяны, которые собрал `--clean`'),
           ('d1106', '«6.11, 18:08 — разбор «отложенного»…»: поправки автора, с которых начат `--clean`'),
           ('d1106', '«6.11, 17:50 — чистка комментариев в каждом узле дерева»'), ('RP', 'проба ответа на повтор (выбор ответа для PL)')],
    'RP': [('PL', '«6.11, 18:16 — ответ на повтор команды: поправка автора»')],
    'NT': [('AGREE', 'разбор согласия: строка «trust your colleague initially»')],
    'VALV': [('d1109', '«План из сообщения 7.11»; «Поправка автора» 14:55 — хвост VAL-V снят'),
             ('d1109', '«9.11, 17:18 — сбой очереди: два задания VAL-V считались дважды»')],
    'PK': [('d1109', '«Поправка автора» 14:55: план — от 6.11'), ('TKK', 'TKK, 6.11')],
    'PKR': [('d1109', '«Починка очереди» (`qj.sh`)'), ('R08', '`--resume` — инструмент 08_IO_R')],
    'TY': [('d1110', '«10.11, 01:05 — ручной стенд»: серии TY и PN отложены')],
    'G1': [('G15C', 'код и запуск G1–G5')], 'G2': [('G15C', 'код и запуск G1–G5')], 'G3': [('G15C', 'код и запуск G1–G5')],
    'G4': [('G15C', 'код и запуск G1–G5')], 'G5': [('G15C', 'код и запуск G1–G5')],
    'G6': [('TD', 'TD, TU, HT — прятанье инструментов 5.11')],
    'T2': [('G7', 'G7 — следующий шаг из разбора развилок')],
    'F1': [('AA', 'тикет: значения для `all(…)` / `any(…)` — из «В очередь» F1')],
    'AA': [('TKV', 'TKV — `--ticket-values`, 6.11'), ('F1', 'F1: «В очередь…»')],
}

CODE_RE = re.compile(r'^\*\*Код (пробы|и запуск)')


def git_lines(path):
    t = subprocess.run(['git', 'show', f'{BASE}:{path}'], capture_output=True, text=True, check=True).stdout
    return t.split('\n')[:-1] if t.endswith('\n') else t.split('\n')


def parse_spec(src, n):
    segs = []
    for row in SPEC[src].split('\n'):
        row = row.strip()
        if not row:
            continue
        rng, key = row.split()
        a, b = (rng.split('-') + [rng])[:2] if '-' in rng else (rng, rng)
        segs.append((int(a), int(b), key))
    pos = 1
    for a, b, k in segs:
        assert a == pos and b >= a, (src, a, b, k, pos)
        assert k in P or k in DAYS, k
        pos = b + 1
    assert pos == n + 1, (src, pos, n)
    return segs


def sections(lines):
    """для каждой строки — номер строки её заголовка (вне блоков кода)"""
    head, fence, cur = {}, False, 1
    for i, s in enumerate(lines, 1):
        if s.startswith('```'):
            fence = not fence
        elif not fence and s.startswith('#'):
            cur = i
        head[i] = cur
    return head


def code_lines(lines, head):
    code, start = set(), {}
    for i, s in enumerate(lines, 1):
        if CODE_RE.match(s):
            start.setdefault(head[i], i)
    for i in range(1, len(lines) + 1):
        h = head[i]
        if h in start and i >= start[h]:
            code.add(i)
    return code, start


def day_of(src, i):
    for a, b, d in DAYRANGE[src]:
        if a <= i <= b:
            return d


def path_of(key):
    return P[key][0] if key in P else DAYS[key][0]


def rel(frm, key):
    return os.path.relpath(path_of(key), os.path.dirname(frm))


def label(key):
    return P[key][1] if key in P else DAYS[key][1]


def htext(s):
    return s.lstrip('#').strip()


def main():
    data = {}
    for src, path in SRC.items():
        lines = git_lines(path)
        head = sections(lines)
        code, cstart = code_lines(lines, head)
        segs = parse_spec(src, len(lines))
        # куски не пересекают границ «текст / код», записей (заголовков) и дней
        out = []
        for a, b, k in segs:
            cur = a
            for i in range(a, b + 1):
                if i > cur and ((i in code) != (cur in code) or head[i] != head[cur] or day_of(src, i) != day_of(src, cur)):
                    out.append((cur, i - 1, k))
                    cur = i
            out.append((cur, b, k))
        data[src] = dict(lines=lines, head=head, code=code, cstart=cstart, segs=out, file=os.path.basename(path))

    owner = {}  # (src, line) → ключ
    for src, d in data.items():
        for a, b, k in d['segs']:
            for i in range(a, b + 1):
                owner[(src, i)] = k

    files = {k: {'text': [], 'code': []} for k in list(P) + list(DAYS)}
    order = ['L03', 'L09', 'L10']

    # файлы проб
    for src in order:
        d = data[src]
        for a, b, k in d['segs']:
            if k in P:
                files[k]['code' if a in d['code'] else 'text'].append((src, a, b))

    def chunk(src, a, b):
        d = data[src]
        return [f'<!-- {d["file"]}:{a}–{b} -->' if a != b else f'<!-- {d["file"]}:{a} -->'] + d['lines'][a - 1:b]

    def gap_links(frm, src, a, b):
        ks = []
        for i in range(a, b + 1):
            k = owner[(src, i)]
            if data[src]['lines'][i - 1].strip() and k not in ks:
                ks.append(k)
        return ', '.join(f'[{label(k)}]({rel(frm, k)})' for k in ks)

    linemap = []
    written = {}
    for k, (path, ident, title) in P.items():
        fp = os.path.join(OUT, path)
        body = [f'# {ident} — {title}', '']
        days = []
        for src, a, b in files[k]['text'] + files[k]['code']:
            dd = day_of(src, a)
            if dd not in days:
                days.append(dd)
        days.sort(key=lambda x: list(DAYS).index(x))
        body.append(f'[Указатель проб](../INDEX.md) · хронология: '
                    + ', '.join(f'[{DAYS[x][1]}]({rel(path, x)})' for x in days)
                    + ' · как устроено — [README](../README.md)')
        body.append('')
        prev = None
        for src, a, b in files[k]['text']:
            d = data[src]
            h = d['head'][a]
            if a != h:
                if prev and prev[0] == src and prev[2] + 1 == a:
                    pass
                elif prev and prev[0] == src and d['head'][prev[2]] == h:
                    body.append(f'*[…] строки этой записи между предыдущим куском и этим — в: {gap_links(path, src, prev[2] + 1, a - 1)}*')
                else:
                    hk = owner[(src, h)]
                    where = '' if hk == k else f'; заголовок и остальное — в [{label(hk)}]({rel(path, hk)})'
                    body.append(f'*Из записи «{htext(d["lines"][h - 1])}» ({d["file"]}{where}):*')
                if not (prev and prev[0] == src and prev[2] + 1 == a):
                    body.append('')
            body += chunk(src, a, b)
            if body[-1].strip():
                body.append('')
            prev = (src, a, b)
            linemap.append((src, a, b, k))
        if files[k]['code']:
            body += ['## Код', '']
            for src, a, b in files[k]['code']:
                d = data[src]
                if a != d['cstart'].get(d['head'][a]):
                    first = d['cstart'][d['head'][a]]
                    fk = owner[(src, first)]
                    note = '' if fk == k else f'; начало блока, с оговоркой о коммите 951bc3b, — в [{label(fk)}]({rel(path, fk)})'
                    body.append(f'*Часть блока «Код пробы» записи «{htext(d["lines"][d["head"][a] - 1])}»{note}:*')
                    body.append('')
                body += chunk(src, a, b)
                if body[-1].strip():
                    body.append('')
                linemap.append((src, a, b, k))
        see = SEE.get(k, [])
        if see:
            body += ['## Связанные записи', '']
            for sk, what in see:
                body.append(f'- [{label(sk)}]({rel(path, sk)}): {what}')
            body.append('')
        written[fp] = body

    # хронология дней
    for dk, (path, dlabel) in DAYS.items():
        fp = os.path.join(OUT, path)
        body = [f'# {dlabel} — хронология', '',
                '[Указатель проб](../INDEX.md) · как устроено — [README](../README.md)', '',
                'Записи дня в порядке журнала. Текст, не относящийся к одной пробе, — здесь дословно; записи о пробах — '
                'в файлах проб, на их месте стоит ссылка «→».', '']
        for src in order:
            d = data[src]
            pend = None  # (ключ, заголовок записи, есть ли код)
            last_h_here = None

            def flush():
                nonlocal pend
                if pend:
                    k, items = pend
                    ln = f'[{label(k)}]({rel(path, k)})'
                    parts = []
                    for h, kind in items:
                        if kind == 'code':
                            parts.append('листинг кода')
                        elif kind == 'frag':
                            parts.append(f'часть записи «{htext(d["lines"][h - 1])}»')
                        else:
                            parts.append(f'«{htext(d["lines"][h - 1])}»')
                    if all(kind == 'code' for _, kind in items):
                        body.append(f'→ листинг кода — в {ln}')
                    else:
                        body.append(f'→ {ln}: ' + '; '.join(parts))
                    body.append('')
                    pend = None

            for a, b, k in d['segs']:
                if day_of(src, a) != dk:
                    continue
                h = d['head'][a]
                if k == dk:
                    flush()
                    if a != h and owner[(src, h)] != dk and last_h_here != h:
                        hk = owner[(src, h)]
                        body.append(f'*Из записи «{htext(d["lines"][h - 1])}» (заголовок — в [{label(hk)}]({rel(path, hk)})):*')
                        body.append('')
                    body += chunk(src, a, b)
                    if body[-1].strip():
                        body.append('')
                    last_h_here = h
                    linemap.append((src, a, b, k))
                else:
                    iscode = a in d['code']
                    kind = 'code' if iscode else ('head' if a == h else 'frag')
                    if pend and pend[0] == k:
                        if iscode and any(hh == h for hh, _ in pend[1]):
                            continue  # листинг той же записи: ссылка на запись уже стоит
                        if not any(hh == h and kk == kind for hh, kk in pend[1]):
                            pend[1].append((h, kind))
                    else:
                        flush()
                        pend = (k, [(h, kind)])
            flush()
        written[fp] = body

    for fp, body in written.items():
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        while body and not body[-1].strip():
            body.pop()
        with open(fp, 'w') as f:
            f.write('\n'.join(body) + '\n')

    # карта старых строк
    linemap.sort(key=lambda x: (order.index(x[0]), x[1]))
    mp = ['# Старые номера строк журналов → новые файлы', '',
          'Для ссылок вида «LAB-1103:953» и «L03:953», оставшихся в тексте записей и в старых документах. '
          'Строки — по коммиту 728e61b (`git show 728e61b:docs/LAB-1103.md`).', '']
    for src in order:
        mp += [f'## {data[src]["file"]}', '', '| строки | файл |', '|---|---|']
        for s, a, b, k in linemap:
            if s == src:
                mp.append(f'| {a}–{b} | [{label(k)}]({path_of(k)}) |' if a != b else f'| {a} | [{label(k)}]({path_of(k)}) |')
        mp.append('')
    with open(os.path.join(OUT, 'OLD-LINES.md'), 'w') as f:
        f.write('\n'.join(mp))
    print(f'файлов проб {len(P)}, дней {len(DAYS)}')


if __name__ == '__main__':
    main()
