# Окружение прогона апстрима, код апстрима не меняется.
# 1. as_completed в порядке создания задач. У апстрима set(fs) раскладывает корутины по адресам (артефакт CPython),
#    и при concurrency 1 они идут в порядке этих адресов; здесь — по списку, как у мостика (DEVIATIONS TF9).
# 2. Клиенты AsyncOpenAI живут до конца процесса. Агент на каждый rollout создаёт свой клиент и не закрывает его;
#    сборщик закрывает сокет мимо цикла событий, номер fd достаётся новому соединению, и цикл его не видит —
#    прогон виснет на connect (воспроизводится на фейковой модели).
import asyncio

import openai

_as_completed = asyncio.as_completed


def as_completed(fs, **kw):
    return _as_completed([asyncio.ensure_future(f) for f in fs], **kw)


asyncio.as_completed = as_completed

_init = openai.AsyncOpenAI.__init__
CLIENTS = []


def init(self, *args, **kwargs):
    _init(self, *args, **kwargs)
    CLIENTS.append(self)


openai.AsyncOpenAI.__init__ = init
