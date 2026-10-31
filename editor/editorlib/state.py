"""Состояние сессии (Run): роль и её инструменты, история, счётчики, правки или предложения, лог."""
import json

from .cfg import F
from . import schema as SC


class Run:
    """Всё, что меняется за сессию. st и items уходят в запись end и возвращаются из run_session."""

    def __init__(self, role, system, first_user, root, prof, seed, log_path, n_obs):
        self.role, self.root, self.prof, self.seed, self.n_obs = role, root, prof, seed, n_obs
        self.tools = SC.role_tools(role)
        self.final_tools = self.tools[1:]
        self.act = "edit" if role == "editor" else "propose"
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": first_user}]
        self.st = {"turns": 0, "tool_calls": 0, "bash_calls": 0, "denied": 0, "repeats": 0, "truncated": 0,
                   "no_call": 0, "bad_call": 0, "max_prompt": 0, "gen_tokens": 0, "model_sec": 0.0, "final_turns": 0,
                   "length_stops": 0, "edits_attempted": 0, "edits_applied": 0, "edit_fail": {}, "proposals": 0,
                   "proposals_rejected": 0}
        self.items = []                  # правки (editor) или предложения (proposer)
        self.seen = {}                   # команда bash -> (номер вызова, вывод); сброс после применённой правки
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
        return self.final_tools if self.final_left else self.tools
