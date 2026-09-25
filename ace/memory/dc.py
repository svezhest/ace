"""Память Dynamic Cheatsheet (dynamic-cheatsheet: dynamic_cheatsheet/language_model.py; промпт куратора
dc_curator.j2 дословно). Вердикта и извлечения нет: память читает сырое (весь ответ генератора) и то, что
показал решатель (добавки input и sheet, extract.Seen).

    Cheatsheet  DC-Cu: один текст целиком; после каждого вопроса куратор (вход задачи, как его видел генератор,
                весь ответ генератора, прошлый текст или "(empty)") пишет новый до 2 * max_tokens; без блока
                <cheatsheet> остаётся старый
    Pairs       DC-RS и контроли: пары (сырой вопрос датасета, весь ответ генератора), только добавляются; sheet —
                последний синтезированный под вопрос cheatsheet (его показ оставляет в промпте попытки)"""
from dataclasses import dataclass

from .. import prompts, render
from ..extract import INPUT, SHEET
from ..model import Call, messages
from ..upstream.dc import CHEATSHEET, MAX_TOKENS, TOKENS, dc_params
from . import Document, Lessons, Operation, Record

CURATOR = prompts.load("dc_curator")
class Sheet(Document):
    """Cheatsheet: до первой записи его нет (показ "(empty)"); записанный пустым показывается пустым,
    как в апстриме."""
    def __init__(self):
        super().__init__(None, "sheet")

    def records(self):
        return [Record(self.kind, self.text)] if self.text is not None else []

    def chars(self):
        return len(self.text or "")

    def dump(self):
        return [dict(kind=self.kind, id=self.kind, text=self.text)] if self.text is not None else []

    def current(self):
        """Текст для промптов куратора и синтеза."""
        return self.text if self.text is not None else render.EMPTY


class Cheatsheet(Sheet):
    requires = frozenset({INPUT})

    def learn(self, ex, extractions):
        for x in extractions:
            ep = x.group.episodes[0]
            fields = {"QUESTION": x.extras[INPUT], "MODEL_ANSWER": ep.output, "PREVIOUS_CHEATSHEET": self.current()}
            call = Call(messages(CURATOR.fill(fields)), dc_params(TOKENS * MAX_TOKENS), CHEATSHEET)
            new = ex.model.ask(call).output
            if new is not None:
                self.rewrite(new)


@dataclass(frozen=True, eq=False)
class Pair(Record):
    """Пара DC-RS: сырой вопрос и решение (text) — весь ответ генератора. Сырой опыт, не меняется."""
    question: str = ""

    def head(self):
        return self.question


class Pairs(Lessons):
    """Пары прошлых вопросов; sheet — последний синтезированный cheatsheet (DC-RS): решатель показал его в попытке
    (добавка sheet), память сохраняет."""
    def __init__(self, sheet=False):
        super().__init__("pair", record=Pair, ops=Operation.ADD)
        self.sheet = Sheet() if sheet else None
        self.requires = frozenset({SHEET}) if sheet else frozenset()

    def learn(self, ex, extractions):
        for x in extractions:
            ep = x.group.episodes[0]
            self.add(ep.output, question=ep.question)
            if self.sheet is not None:
                self.sheet.rewrite(x.extras[SHEET])

    def chars(self):
        return super().chars() + (self.sheet.chars() if self.sheet else 0)

    def key(self):
        return super().key(), self.sheet.key() if self.sheet else None

    def dump(self):
        return super().dump() + (self.sheet.dump() if self.sheet else [])
