"""Состояние сессии (Run): история, счётчики, правки, лог."""
import json

from .cfg import F
from . import schema as SC


class Run:
    """Всё, что меняется за сессию. st и items уходят в запись end и возвращаются из run_session."""

    def __init__(self, system, first_user, root, prof, seed, log_path):
        self.root, self.prof, self.seed = root, prof, seed
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": first_user}]
        self.st = {"turns": 0, "tool_calls": 0, "bash_calls": 0, "denied": 0, "repeats": 0, "truncated": 0,
                   "no_call": 0, "bad_call": 0, "max_prompt": 0, "gen_tokens": 0, "model_sec": 0.0, "final_turns": 0,
                   "length_stops": 0, "edits_attempted": 0, "edits_applied": 0, "edit_fail": {}}
        self.items = []                  # правки: и применённые, и отказы
        self.seen = {}                   # команда bash -> (номер вызова, вывод); сброс после применённой правки
        self.smoke0 = None               # что харнесс добавляет в разговор на заглушке до правок (gate.smoke_added)
        self.final_left, self.final_why = 0, None
        self.last_prompt = self.pending = 0      # pending = оценка токенов, добавленных после последнего ответа
        self.log = open(log_path, "w", encoding="utf-8", errors="backslashreplace")

    def w(self, rec):
        self.log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.log.flush()

    def est(self):
        """Оценка промпта следующего запроса."""
        return self.last_prompt + self.pending

    def note_user(self, text):
        self.messages.append({"role": "user", "content": text})
        self.pending += F.est_tokens(text) + 10
        self.w({"type": "note", "text": text})

    def offered(self):
        """Инструменты этого хода: в финальных ходах — без bash."""
        return SC.TOOLS[1:] if self.final_left else SC.TOOLS
