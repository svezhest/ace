"""python run.py TASK METHOD [N] [OUT]"""
import sys

from ace.loop import run
from ace.methods import METHODS
from ace.model import Model
from ace.tasks import TASKS

task, method = TASKS[sys.argv[1]], METHODS[sys.argv[2]]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 40
out = sys.argv[4] if len(sys.argv) > 4 else f"results/{task.name}{n}/{method.name}"
print(run(task, method, Model(), n, out))
