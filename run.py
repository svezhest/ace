"""python run.py TASK METHOD [N] [OUT]; протокол — метода (по его апстриму), EPOCHS=3 и OFFLINE=1 меняют его
только в этом прогоне (ace/config.py); утечку метки сборка не пропустит."""
import sys
from dataclasses import replace

from ace import config
from ace.learner import swap
from ace.loop import run
from ace.methods import METHODS
from ace.model import Model
from ace.tasks import TASKS

task, method = TASKS[sys.argv[1]], METHODS[sys.argv[2]]
if config.EPOCHS or config.OFFLINE:
    offline = config.OFFLINE or method.protocol.offline
    method = swap(method, protocol=replace(method.protocol, epochs=config.EPOCHS or method.protocol.epochs, offline=offline,
                                           window=0 if offline else method.protocol.window))
n = int(sys.argv[3]) if len(sys.argv) > 3 else config.SIZE
out = sys.argv[4] if len(sys.argv) > 4 else f"{config.RESULTS}/{task.name}{n}/{method.name}"
print(run(task, method, Model(), n, out))
