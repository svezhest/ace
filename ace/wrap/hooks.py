"""Хуки по ошибкам инструментов: обёртка Hooks(ученик) — рядом с учеником второй ученик-хуки со своим конвейером
(извлечение extract/hooks.py, память memory/hooks.py, та же сверка стыка и добавок) и показ хуков (show/hooks.py)
поверх показа ученика.

    learn="model"   уроки по ошибкам попытки выводит модель; learn="raw" — ошибка и следующий вызов, который прошёл
    show="after"    после шага с ошибкой исполнения хуки с её trigger — сообщением в конец истории (Patch(append)):
                    исправление. Исход — по первому шагу следующего ответа модели (Patch встаёт после всех шагов
                    ответа): помог, если его ошибка не повторилась; без следующего шага исхода нет
    show="system"   все хуки в системном промпте с начала попытки: предотвращение. Исход — по попытке: помог, если
                    его ошибки в ней не было
Исходы показа (fired) — метки хуков. Учатся хуки только на ошибках исполнения (traceback), не на отбивках вызова
инструмента. Ошибки шага бывают только у решателя с инструментами: ученику нужна среда с исполнением кода."""
from ..extract.hooks import LEARN, FromErrors, error_steps
from ..learner import Learner
from ..loop import combine
from ..memory.hooks import PRUNE, HookBook
from ..show.hooks import AFTER, SYSTEM, fired
from . import Wrapper


def helped(hook, step):
    """Исход показа по следующему шагу: помог, если шаг не упал с ошибкой хука."""
    return not (step.exec_error and hook.fires(step.result))


class Hooks(Wrapper):
    def __init__(self, inner, name=None, learn="model", prune=PRUNE, show="after"):
        super().__init__(inner, name)
        self.book = Learner(f"{self.name}: хуки", memory=HookBook(prune), extract=FromErrors(LEARN[learn]))
        self.show_at = show
        self.waiting = None         # (попытка, номер ответа, id хуков, показанных после него) — ждут исхода

    @property
    def hooks(self):
        return self.book.memory

    def check(self):
        if self.inner.solver is not None:
            raise ValueError(f"{self.name}: хуки по ошибкам инструментов при своём решателе метода не действуют")

    def prompt(self, ex, item, k, memory=None):
        prompt = self.inner.prompt(ex, item, k, memory)
        if self.show_at == "system":
            mine = SYSTEM.prompt(ex, self.hooks, item, k)
            prompt.system += mine.system
            prompt.shown = prompt.shown + mine.shown
        return prompt

    @property
    def watches_steps(self):
        return True

    def on_step(self, ex, attempt, step):
        patch = self.inner.on_step(ex, attempt, step)
        if self.show_at != "after":
            return patch
        turn = attempt.turns[-1] if attempt.turns else len(attempt.steps)
        if self.waiting and self.waiting[0] is attempt and self.waiting[1] < turn:
            # первый шаг следующего ответа модели: хук помог, если его ошибка не повторилась
            for rid in self.waiting[2]:
                hook = self.hooks.get(rid)
                if hook is not None:
                    attempt.fired.append((rid, helped(hook, step)))
            self.waiting = None
        shown = [r.id for r in fired(self.hooks.records(), step)]
        if shown:
            if self.waiting and self.waiting[0] is attempt:
                self.waiting[2].extend(shown)
            else:
                self.waiting = (attempt, turn, shown)
        return combine(patch, AFTER.on_step(ex, self.hooks, attempt, step))

    def on_attempt(self, ex, episode):
        self.inner.on_attempt(ex, episode)
        if self.show_at == "system":
            errors = [s.result for s in error_steps(episode)]
            for rid in episode.shown:
                hook = self.hooks.get(rid)
                if hook is not None:
                    episode.fired.append((rid, not any(hook.fires(e) for e in errors)))

    def on_question(self, ex, group):
        self.inner.on_question(ex, group)
        self.book.on_question(ex, group)

    def on_batch(self, ex, groups):
        self.inner.on_batch(ex, groups)
        self.book.on_batch(ex, groups)

    def on_pass(self, ex):
        self.inner.on_pass(ex)
        self.book.on_pass(ex)

    def snapshot(self):
        return self.inner.snapshot(), self.book.snapshot()

    def restore(self, snapshot):
        self.inner.restore(snapshot[0])
        self.book.restore(snapshot[1])

    def key(self):
        key = self.inner.key()
        return None if key is None else (key, self.hooks.key())

    def dump(self):
        return self.inner.dump() + self.hooks.dump()
