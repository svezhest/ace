"""Dynamic Cheatsheet (dynamic-cheatsheet: dynamic_cheatsheet/language_model.py, run_benchmark.py).
Промпты куратора и синтеза апстрима дословно в ace/prompts/dc_*.j2. Вердикта нет, извлечения нет: память
читает сырое (вопрос и весь ответ решателя).

dc (DC-Cu) — мир документов:
    память      один текст (cheatsheet) целиком; после каждого вопроса куратор (вопрос, весь ответ решателя,
                прошлый текст или "(empty)") пишет новый; без блока <cheatsheet> остаётся старый
    показ       весь текст, пустой — "(empty)"
dc_code — то же с исполнением кода: в апстриме оно включено по умолчанию (execute_python_code=True),
    процесс на каждый вызов — у нас контейнер на вызов.

dc_rs (DC-RS):
    память      пары (вопрос, весь ответ решателя), только добавляются, и последний синтезированный cheatsheet
    показ       top-3 прошлых пары по близости вопросов (BGE-M3; в апстриме готовые эмбеддинги из
                embeddings/<task>.csv) в оформлении PREVIOUS SOLUTIONS, самая похожая последней; из них и
                прошлого cheatsheet модель синтезирует cheatsheet под вопрос, и на первом вопросе тоже (пары
                "(empty)"); без блока <cheatsheet> решатель видит сами пары, и они же сохраняются как
                cheatsheet (extract_cheatsheet(old_cheatsheet=пары), как в апстриме)
Контроли апстрима: dc_retrieval — пары без синтеза (Dynamic_Retrieval), dc_history — все прошлые пары подряд
(FullHistoryAppending).
Куратор и синтез в апстриме пишут до 2 * max_tokens."""
from dataclasses import dataclass

from .. import parse, prompts, render, verdict
from ..env import Sandbox
from ..extract import Raw
from ..learner import Learner, swap
from ..loop import Prompt
from ..memory import Document, Lessons, Operation, Record
from ..show import Synth, TopK, Whole

SYNTH, CURATOR = prompts.load("dc_synth"), prompts.load("dc_curator")
NOTE = prompts.text("dc_note")
EMPTY = render.EMPTY
CHEATSHEET = parse.opened("cheatsheet")
TOP = 3
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
        return self.text if self.text is not None else EMPTY

# dc


class Cheatsheet(Sheet):
    def learn(self, ex, extractions):
        for x in extractions:
            ep = x.group.episodes[0]
            fields = {"QUESTION": ep.question, "MODEL_ANSWER": ep.output, "PREVIOUS_CHEATSHEET": self.current()}
            new = CHEATSHEET(ex.model.run("", CURATOR.fill(fields), max_tokens=TOKENS * ex.model.max_tokens).output)
            if new is not None:
                self.rewrite(new)


dc = Learner("dc", memory=Cheatsheet(), show=Whole(line=render.plain, empty=EMPTY), extract=Raw(), verdict=verdict.none)
dc_code = swap(dc, "dc_code", env=Sandbox())

# dc_rs и контроли


@dataclass(frozen=True, eq=False)
class Pair(Record):
    """Пара DC-RS: вопрос и решение (text) — весь ответ решателя. Сырой опыт, не меняется."""
    question: str = ""

    def head(self):
        return self.question


class Pairs(Lessons):
    """Пары прошлых вопросов; sheet — последний синтезированный cheatsheet (DC-RS): его показ оставляет в
    промпте попытки, память сохраняет."""
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


@dataclass
class SheetPrompt(Prompt):
    sheet: str = ""             # синтезированный под вопрос cheatsheet (или пары, если синтез не разобрался)


class Synthesis(Synth):
    def shown(self, text, recs):
        p = super().shown(text, recs)
        return SheetPrompt(p.system, shown=p.shown, sheet=text)


def pairs_and_sheet(text, memory, item):
    return {"PREVIOUS_INPUT_OUTPUT_PAIRS": text, "NEXT_INPUT": item["context"], "PREVIOUS_CHEATSHEET": memory.sheet.current()}


retrieval = TopK(TOP, key=lambda r: r.question, layout=lambda recs, memory: render.pairs(recs, True, NOTE), empty=EMPTY)
history = Whole(layout=lambda recs, memory: render.pairs(recs, False), empty=EMPTY)

dc_rs = Learner("dc_rs", memory=Pairs(sheet=True), show=Synthesis(retrieval, SYNTH, pairs_and_sheet, CHEATSHEET, TOKENS),
                extract=Raw(), verdict=verdict.none)
dc_retrieval = Learner("dc_retrieval", memory=Pairs(), show=retrieval, extract=Raw(), verdict=verdict.none)
dc_history = swap(dc_retrieval, "dc_history", show=history)
