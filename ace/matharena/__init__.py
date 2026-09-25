"""Проверка ответов MathArena (github.com/eth-sri/matharena @ e927660 — последний коммит до коммита EvoLib, MIT,
Copyright (c) 2024 SRI Lab, ETH Zurich): parser.py и parse_manual.py дословно, только импорт parse_manual
относительный. grade — extract_and_grade из grader.py для соревнования с ответом, как HMMT
(configs/competitions/hmmt/*.yaml: strict_parsing false): без Lean, точного совпадения, hash-ответов и
предупреждений — на верность они не влияют."""
from .parser import check_answers, extract_answer, parse_answer


def grade(text, gold):
    """Верен ли ответ, извлечённый из текста решения, эталону gold (строка; с запятой — список)."""
    is_list = "," in gold
    answer, _ = extract_answer(text, strict_parsing=False, parse=True, list_answer=is_list)
    typed, _ = parse_answer(gold, list_answer=is_list)
    return check_answers(answer, typed)
