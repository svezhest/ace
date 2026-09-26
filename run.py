"""python run.py TASK METHOD [N] [OUT]; OUT по умолчанию — results/<задача><N>/<метод>/<протокол>_<модель>_<бэкенд>;
протокол — метода (по его апстриму), EPOCHS=3 и OFFLINE=1 меняют его
только в этом прогоне (ace/config.py); утечку метки сборка не пропустит."""
import sys
from dataclasses import replace

from ace import config
from ace.learner import swap
from ace.loop import folder, run
from ace.methods import METHODS
from ace.model import Model
from ace.tasks import TASKS

task, method = TASKS[sys.argv[1]], METHODS[sys.argv[2]]
if config.EPOCHS or config.OFFLINE:
    offline = config.OFFLINE or method.protocol.offline
    epochs = config.EPOCHS or method.protocol.epochs
    window = 0 if offline else method.protocol.window
    method = swap(method, protocol=replace(method.protocol, epochs=epochs, offline=offline, window=window))
n = int(sys.argv[3]) if len(sys.argv) > 3 else task.size()
model = Model()
out = sys.argv[4] if len(sys.argv) > 4 else folder(task, n, method, model)
print(run(task, method, model, n, out))
