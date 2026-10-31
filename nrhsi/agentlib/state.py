"""Состояние сессии (Run): инструменты роли, история, счётчики, финальные ходы, лог."""
import json
import os

from . import cfg as C
from . import model as MO
from . import sandbox as SB


class Run:
    """Всё, что меняется за сессию. Профиль песочницы — рядом с каталогом, удаляет его session."""

    def __init__(self, system, first_user, role_tools, handle, root, log_path, bash_limit, final_msg, seed):
        self.root = os.path.realpath(root)
        self.role_tools, self.handle = role_tools, handle
        self.bash_limit, self.final_msg, self.seed = bash_limit, final_msg, seed
        self.tools = [C.BASH_TOOL] + role_tools + [C.FINISH_TOOL]
        self.final_tools = role_tools + [C.FINISH_TOOL]
        self.prof = SB.sandbox_profile(self.root)
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": first_user}]
        self.seen = set()                # команды bash (пробелы схлопнуты); сброс после принятого edit
        self.repeats, self.bash_calls, self.no_call, self.turns = 0, 0, 0, 0
        self.final_left = self.fix_left = 0
        self.est = 0                     # оценка промпта следующего запроса
        self.rejected = False            # в этом ходе отклонён вызов инструмента роли
        self.log = open(log_path, "w", encoding="utf-8")

    def w(self, rec):
        self.log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.log.flush()

    def say(self, text):
        self.messages.append({"role": "user", "content": text})
        self.est += MO.est_tokens(text)

    def offered(self):
        """Инструменты этого хода: в финальных ходах — без bash."""
        return self.final_tools if self.final_left else self.tools
