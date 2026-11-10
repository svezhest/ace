#!/usr/bin/env python3
"""Проверка переноса журналов: ничего не потеряно, ничего не продублировано, нового текста — только связки.

Старые журналы берутся из git (по умолчанию 728e61b), новые — файлы проб и дней в docs/lab/
(INDEX.md, README.md, OLD-LINES.md и tools/ не считаются: в них текста журнала быть не должно).

1. Каждая непустая строка старых LAB-1103.md, LAB-1109.md, LAB-1110.md есть в новых файлах столько же раз,
   сколько в старых (сравнение строк целиком, байт в байт).
2. Ни одна строка старых журналов не встречается в новых чаще, чем в старых (дублей нет).
3. Строки новых файлов, которых нет в старых, — только служебные: заголовок файла, ссылки, связки, отметки строк.

Запуск из корня репозитория: python3 docs/lab/tools/check.py [коммит]
"""
import collections
import glob
import re
import subprocess
import sys

BASE = sys.argv[1] if len(sys.argv) > 1 else '728e61b'
OLD = ['docs/LAB-1103.md', 'docs/LAB-1109.md', 'docs/LAB-1110.md']
NEW = sorted(f for f in glob.glob('docs/lab/**/*.md', recursive=True)
             if not re.search(r'docs/lab/(INDEX|README|OLD-LINES)\.md$|/tools/', f))

SERVICE = [  # виды нового текста
    (r'^<!-- LAB-11(03|09|10)\.md:\d+(–\d+)? -->$', 'отметка строк старого файла'),
    (r'^# .+ — ', 'заголовок файла'),
    (r'^\[Указатель проб\]\(\.\./INDEX\.md\)', 'строка ссылок под заголовком'),
    (r'^Записи дня в порядке журнала\.', 'пояснение в начале дня'),
    (r'^\*Из записи «.*»( \(.*\))?:\*$', 'связка «Из записи …»'),
    (r'^\*\[…\] строки этой записи между', 'отметка пропуска'),
    (r'^\*Часть блока «Код пробы»', 'связка к части листинга'),
    (r'^→ ', 'ссылка из хронологии дня на файл пробы'),
    (r'^## (Код|Связанные записи)$', 'раздел файла пробы'),
    (r'^- \[[^\]]+\]\([^)]+\): ', 'строка «Связанные записи»'),
]


def old_lines():
    out = []
    for p in OLD:
        t = subprocess.run(['git', 'show', f'{BASE}:{p}'], capture_output=True, text=True, check=True).stdout
        out += [(p, i, s) for i, s in enumerate(t.split('\n'), 1) if s.strip()]
    return out


def main():
    old = old_lines()
    oldc = collections.Counter(s for _, _, s in old)
    newc = collections.Counter()
    for f in NEW:
        for s in open(f).read().split('\n'):
            if s.strip():
                newc[s] += 1

    missing = []
    seen = collections.Counter()
    for p, i, s in old:
        seen[s] += 1
        if seen[s] > newc[s]:
            missing.append((p, i, s))
    dup = {s: (newc[s], oldc[s]) for s in oldc if newc[s] > oldc[s]}

    kinds = collections.Counter()
    other = []
    for s, n in newc.items():
        if s in oldc:
            continue
        for rx, kind in SERVICE:
            if re.search(rx, s):
                kinds[kind] += n
                break
        else:
            other.append(s)

    print(f'Проверка переноса журналов (старые — {BASE}, новые — {len(NEW)} файлов в docs/lab/)')
    for p in OLD:
        n = sum(1 for q, _, _ in old if q == p)
        print(f'  {p}: непустых строк {n}')
    print(f'  всего непустых строк в старых журналах: {len(old)}')
    print(f'Неразмещённых строк: {len(missing)}')
    for p, i, s in missing[:50]:
        print(f'  {p}:{i}: {s[:120]}')
    print(f'Строк старых журналов, которые в новых встречаются чаще, чем в старых (дубли): {len(dup)}')
    for s, (a, b) in list(dup.items())[:50]:
        print(f'  {a} против {b}: {s[:120]}')
    print('Новый текст (строк, которых нет в старых журналах), по видам:')
    for kind, n in kinds.most_common():
        print(f'  {kind}: {n}')
    print(f'  прочее (не служебное): {len(other)}')
    for s in other[:50]:
        print(f'    {s[:140]}')
    return 1 if missing or dup or other else 0


if __name__ == '__main__':
    sys.exit(main())
