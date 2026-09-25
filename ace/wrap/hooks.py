"""Хуки по ошибкам инструментов: обёртка Hooks(ученик) = извлечение (extract/hooks.py) + память (memory/hooks.py) +
показ (show/hooks.py) поверх любого ученика.

    learn="model"   уроки по ошибкам попытки выводит модель; learn="raw" — ошибка и следующий вызов, который прошёл
    show="after"    после шага с ошибкой исполнения хуки с её trigger — сообщением в конец истории (Patch(append)):
                    исправление. Исход — по первому шагу следующего ответа модели (Patch встаёт после всех шагов
                    ответа): помог, если его ошибка не повторилась; без следующего шага исхода нет
    show="system"   все хуки в системном промпте с начала попытки: предотвращение. Исход — по попытке: помог, если
                    его ошибки в ней не было
Исходы показа (fired) — метки хуков. Учатся хуки только на ошибках исполнения (traceback), не на отбивках вызова
инструмента. Ошибки шага бывают только у решателя с инструментами: ученику нужна среда с исполнением кода."""
import copy

from ..extract import missing
from ..extract.hooks import LEARN, FromErrors, failures
from ..memory.hooks import PRUNE, HookBook
from ..show.hooks import AFTER, SYSTEM, fired
from . import Wrapper


class Hooks(Wrapper):
    def __init__(self, inner, name=None, learn="model", prune=PRUNE, show="after"):
        super().__init__(inner, name)
        self.hooks, self.extract_hooks, self.show_at = HookBook(prune), FromErrors(LEARN[learn]), show
        self.pending_hooks = []
        self.waiting = None         # (попытка, ответ, id хуков, показанных после него) — ждут исхода
        lack = missing(self.hooks, self.extract_hooks)
        if lack:
            raise ValueError(f"{self.name}: память хуков требует {', '.join(sorted(lack))}")

    def check(self):
        if self.inner.solver is not None:
            raise ValueError(f"{self.name}: хуки по ошибкам инструментов при своём решателе метода не действуют")

    def prompt(self, ex, item, k, memory=None):
        p = self.inner.prompt(ex, item, k, memory)
        if self.show_at == "system":
            mine = SYSTEM.prompt(ex, self.hooks, item, k)
            p.system += mine.system
            p.shown = p.shown + mine.shown
        return p

    def watches_steps(self):
        return True

    def on_step(self, ex, attempt, step):
        patch = self.inner.on_step(ex, attempt, step)
        if self.show_at != "after":
            return patch
        turn = attempt.turns[-1] if attempt.turns else len(attempt.steps)
        if self.waiting and self.waiting[0] is attempt and self.waiting[1] < turn:
            attempt.fired += [(id, not (step.exec_error and self.hooks.get(id).fires(step.result)))
                              for id in self.waiting[2] if self.hooks.get(id)]
            self.waiting = None
        shown = [r.id for r in fired(self.hooks.records(), step)]
        if shown:
            if self.waiting and self.waiting[0] is attempt:
                self.waiting[2].extend(shown)
            else:
                self.waiting = (attempt, turn, shown)
        mine = AFTER.on_step(ex, self.hooks, attempt, step)
        return mine if patch is None else patch.merge(mine) if mine else patch

    def on_attempt(self, ex, episode):
        self.inner.on_attempt(ex, episode)
        if self.show_at == "system":
            errors = [s.result for s in failures(episode)]
            episode.fired += [(id, not any(self.hooks.get(id).fires(e) for e in errors))
                              for id in episode.shown if self.hooks.get(id)]

    def on_question(self, ex, group):
        self.inner.on_question(ex, group)
        x = self.extract_hooks(ex, group, self.hooks)
        if x:
            self.pending_hooks.append(x)

    def on_batch(self, ex, groups):
        self.inner.on_batch(ex, groups)
        if self.pending_hooks:
            self.hooks.learn(ex, self.pending_hooks)
        self.pending_hooks = []

    def on_pass(self, ex):
        self.inner.on_pass(ex)
        self.pending_hooks = []

    def snapshot(self):
        return self.inner.snapshot(), copy.deepcopy(self.hooks)

    def restore(self, snapshot):
        self.inner.restore(snapshot[0])
        self.hooks = copy.deepcopy(snapshot[1])

    def key(self):
        key = self.inner.key()
        return None if key is None else (key, self.hooks.key())

    def dump(self):
        return self.inner.dump() + self.hooks.dump()
