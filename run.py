"""python run.py TASK METHOD [N] [OUT]; EPOCHS=3 OFFLINE=1 меняют протокол (ace/config.py)"""
import sys

from ace import config
from ace.loop import run
from ace.methods import METHODS
from ace.model import Model
from ace.tasks import TASKS

task, method = TASKS[sys.argv[1]], METHODS[sys.argv[2]]
n = int(sys.argv[3]) if len(sys.argv) > 3 else config.SIZE
out = sys.argv[4] if len(sys.argv) > 4 else f"{config.RESULTS}/{task.name}{n}/{method.name}"
print(run(task, method, Model(), n, out, epochs=config.EPOCHS, offline=config.OFFLINE))
