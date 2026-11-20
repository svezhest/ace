"""R1b (20.11): строки вывода, где программа сама печатает значение и ожидание («X (want Y)», «-> X (expect Y)»), а
они не совпадают. Инструмент агента: харнесс писателя дописывает к выводу одну строку-факт, вывод модели не толкует."""
import re

# литерал (True/False/None, число, строка в кавычках) перед «(want …» / «[expect …» и литерал-ожидание после
LIT = r"(True|False|None|-?\d+(?:\.\d+)?|'[^'\n]{0,40}'|\"[^\"\n]{0,40}\")"
PAT = re.compile(LIT + r"[\s,;]*[\(\[]\s*(?:want|wanted|expect|expected|should be)\b\s*[:=]?\s*" + LIT)


def note(out):
    """-> строка для конца вывода или ''. Только строки с ожиданием; совпавшие тоже считаются (знаменатель)."""
    hits = [(l, m) for l in out.splitlines() for m in [PAT.search(l)] if m]
    bad = [l.strip() for l, m in hits if m.group(1).strip("'\"") != m.group(2).strip("'\"")]
    if not bad:
        return ""
    shown = "\n".join(f"  {l}" for l in bad[:5])
    return (f"\n\n[harness] {len(bad)} of the {len(hits)} printed lines that state an expected value show a different "
            f"value:\n{shown}")


if __name__ == "__main__":
    t = ("run8 step9 window len: 3 -> periodic? False (want False)\nrun20 step9 window len: 3 -> periodic? False (want False)\n"
         "run7 step12 window len: 9 -> periodic? False (want True)\n")
    print(repr(note(t)))
    print(repr(note("A,B,C,A -> True (expect False)\nsingle -> True (expect True)\nA,B,C,D,A,B -> True (expect False, period-4)")))
    print(repr(note("all good -> 3 (want 3)")))
