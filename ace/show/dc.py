"""Показ Dynamic Cheatsheet (dynamic-cheatsheet; промпты dc_synth.j2, dc_note.j2 дословно).

    SHEET       dc: весь текст, пустой — "(empty)"
    retrieval   top-3 прошлых пары по близости вопросов (BGE-M3) в оформлении PREVIOUS SOLUTIONS, самая похожая
                последней (dc_retrieval)
    SYNTHESIS   dc_rs: из retrieval и прошлого cheatsheet модель синтезирует cheatsheet под вопрос, и на первом
                вопросе тоже (пары "(empty)"); без блока <cheatsheet> решатель видит сами пары, и они же
                сохраняются как cheatsheet (extract_cheatsheet(old_cheatsheet=пары), как в апстриме)
    history     все прошлые пары подряд (dc_history, FullHistoryAppending)"""
from dataclasses import dataclass

from .. import prompts, render
from ..loop import Prompt
from ..memory.dc import CHEATSHEET
from ..memory.dc import TOKENS
from . import Synth, TopK, Whole

SYNTH = prompts.load("dc_synth")
NOTE = prompts.text("dc_note")
TOP = 3


@dataclass
class SheetPrompt(Prompt):
    sheet: str = ""             # синтезированный под вопрос cheatsheet (или пары, если синтез не разобрался)


class Synthesis(Synth):
    def shown(self, text, recs):
        p = super().shown(text, recs)
        return SheetPrompt(p.system, shown=p.shown, sheet=text)


def pairs_and_sheet(text, memory, item):
    return {"PREVIOUS_INPUT_OUTPUT_PAIRS": text, "NEXT_INPUT": item["context"], "PREVIOUS_CHEATSHEET": memory.sheet.current()}


SHEET = Whole(line=render.plain, empty=render.EMPTY)
retrieval = TopK(TOP, key=lambda r: r.question, layout=lambda recs, memory: render.pairs(recs, True, NOTE), empty=render.EMPTY)
history = Whole(layout=lambda recs, memory: render.pairs(recs, False), empty=render.EMPTY)
SYNTHESIS = Synthesis(retrieval, SYNTH, pairs_and_sheet, CHEATSHEET, TOKENS)
