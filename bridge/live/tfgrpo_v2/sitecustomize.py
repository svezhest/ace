# Окружение прогона апстрима, код апстрима не меняется.
# Клиенты AsyncOpenAI живут до конца процесса. Агент на каждый rollout создаёт свой клиент и не закрывает его;
# сборщик закрывает сокет мимо цикла событий, номер fd достаётся новому соединению, и цикл его не видит —
# прогон виснет на connect (воспроизводится на фейковой модели).
import openai

_init = openai.AsyncOpenAI.__init__
CLIENTS = []


def init(self, *args, **kwargs):
    _init(self, *args, **kwargs)
    CLIENTS.append(self)


openai.AsyncOpenAI.__init__ = init
