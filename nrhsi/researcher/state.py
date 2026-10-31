"""Состояние сессии (Run): история, учёт выводов инструментов, счётчики фаз; снимок и продолжение с него."""
import json
import os

from . import cfg as C
from . import prompt as P
from . import model as M


class Run:
    """Всё, что меняется за сессию. st и reports — те же объекты, что у session (уходят в запись end).
    v3b: resume — снимок (SNAPSHOT_DIR): история и счётчики продолжаются с него."""

    def __init__(self, st, reports, w, root, prof, temp, seed, resume=None):
        self.st, self.reports, self.w = st, reports, w
        self.root, self.prof, self.temp, self.seed = root, prof, temp, seed
        self.messages = [{"role": "system", "content": P.SYSTEM}, {"role": "user", "content": P.first_user()}]
        self.seen_cmds = {}              # команда -> (номер вызова, индекс tool-сообщения)
        self.tool_msgs = []              # индексы tool-сообщений в messages по порядку
        self.tool_meta = {}              # v3b: индекс tool-сообщения -> (номер вызова, команда или имя инструмента)
        self.cleared = set()
        self.last_prompt, self.pending = 0, 0    # pending = оценка токенов, добавленных после последнего ответа
        self.warned_ctx = self.warned_steps = False
        self.since_report = 0
        self.final_left, self.final_why = 0, None
        self.turn0 = 0
        self.hyps = []                   # 29.10 (R1): реестр гипотез
        self.rejected_now = 0            # A1: отклонённых report в текущем ответе
        self.accepted_now = 0            # A1: принятых report в текущем ответе
        self.pend = False                # A1: в финале есть отклонённый report, после которого не было хода с принятым без отказов
        self.fix_left = C.FINAL_FIX_TURNS    # A1: сколько ходов финала ещё можно не расходовать из-за отклонённого report
        self.repeat_run = 0              # 29.10 (REPEAT_STOP): повторов подряд (сбрасывает любой вызов, кроме повтора)
        self.drafts = {}                 # 31.10 (nudge): точка предотчёта -> число report в ней
        self.nudge_prev = False          # 1.11 (nudge): прошлый bash/runs был отказом отбивки
        self.loop_hit = False            # 29.10: повторов подряд стало REPEAT_STOP -> финал в конце хода
        if resume:
            self.messages = resume["messages"]
            self.seen_cmds = {k: tuple(v) for k, v in resume["seen_cmds"].items()}
            self.tool_msgs = list(resume["tool_msgs"])
            self.tool_meta = {int(k): tuple(v) for k, v in resume["tool_meta"].items()}
            self.cleared = set(resume["cleared"])
            self.last_prompt, self.pending = resume["last_prompt"], resume["pending"]
            self.warned_ctx, self.warned_steps = resume["warned_ctx"], resume["warned_steps"]
            self.since_report = resume["since_report"]
            st.update(resume["st"])
            reports.extend(resume["reports"])
            self.turn0 = st["turns"]
        self.reads_acc = {r: set(v) for r, v in (resume or {}).get("reads_acc", {}).items()}
        self.scanned_acc = set((resume or {}).get("scanned_acc", []))
        self.seen_acc = {r: set(v) for r, v in (resume or {}).get("seen_acc", {}).items()}

    def est(self):
        """Оценка промпта следующего запроса."""
        return self.last_prompt + self.pending

    def note_user(self, text):
        self.messages.append({"role": "user", "content": text})
        self.pending += M.est_tokens(text)
        self.w({"type": "note", "text": text})

    def snapshot(self, snap_name):
        os.makedirs(C.SNAPSHOT_DIR, exist_ok=True)
        snap = {"name": f"{snap_name}_T{self.st['turns']}", "messages": self.messages, "seen_cmds": self.seen_cmds,
                "tool_msgs": self.tool_msgs, "tool_meta": self.tool_meta, "cleared": sorted(self.cleared),
                "last_prompt": self.last_prompt, "pending": self.pending, "warned_ctx": self.warned_ctx,
                "warned_steps": self.warned_steps, "since_report": self.since_report, "st": self.st,
                "reports": self.reports,
                "reads_acc": {r: sorted(v) for r, v in self.reads_acc.items()}, "scanned_acc": sorted(self.scanned_acc),
                "seen_acc": {r: sorted(v) for r, v in self.seen_acc.items()}}
        path = f"{C.SNAPSHOT_DIR}/{snap['name']}.json"
        with open(path, "w") as f:
            json.dump(snap, f, ensure_ascii=False)
        self.w({"type": "note", "text": f"[harness] snapshot {path}"})
