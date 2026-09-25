"""Память Dynamic Cheatsheet (dynamic-cheatsheet: dynamic_cheatsheet/language_model.py; промпт куратора
dc_curator.j2 дословно). Вердикта и извлечения нет: память читает сырое — вопрос и весь ответ решателя.

    Cheatsheet  DC-Cu: один текст целиком; после каждого вопроса куратор (вопрос, весь ответ решателя, прошлый
                текст или "(empty)") пишет новый до 2 * max_tokens; без блока <cheatsheet> остаётся старый
    Pairs       DC-RS и контроли: пары (вопрос, весь ответ решателя), только добавляются; sheet — последний
                синтезированный под вопрос cheatsheet (его показ оставляет в промпте попытки)"""
from dataclasses import dataclass

from .. import parse, prompts, render
from . import Document, Lessons, Operation, Record

CURATOR = prompts.load("dc_curator")
CHEATSHEET = parse.opened("cheatsheet")
TOKENS = 2                  # куратор и синтез пишут до 2 * max_tokens, как в апстриме


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
    def learn(self, ex, extractions):
        for x in extractions:
            ep = x.group.episodes[0]
            fields = {"QUESTION": ep.question, "MODEL_ANSWER": ep.output, "PREVIOUS_CHEATSHEET": self.current()}
            new = CHEATSHEET(ex.model.run("", CURATOR.fill(fields), max_tokens=TOKENS * ex.model.max_tokens).output)
            if new is not None:
                self.rewrite(new)


@dataclass(frozen=True, eq=False)
class Pair(Record):
    """Пара DC-RS: вопрос и решение (text) — весь ответ решателя. Сырой опыт, не меняется."""
    question: str = ""

    def head(self):
        return self.question


class Pairs(Lessons):
    """Пары прошлых вопросов; sheet — последний синтезированный cheatsheet (DC-RS): показ кладёт его в промпт
    попытки (prompt.sheet), память сохраняет."""
    def __init__(self, sheet=False):
        super().__init__("pair", record=Pair, ops=Operation.ADD)
        self.sheet = Sheet() if sheet else None

    def learn(self, ex, extractions):
        for x in extractions:
            ep = x.group.episodes[0]
            self.add(ep.output, question=ep.question)
            if self.sheet is not None:
                self.sheet.rewrite(ep.prompt.sheet)

    def chars(self):
        return super().chars() + (self.sheet.chars() if self.sheet else 0)

    def key(self):
        return super().key(), self.sheet.key() if self.sheet else None

    def dump(self):
        return super().dump() + (self.sheet.dump() if self.sheet else [])
