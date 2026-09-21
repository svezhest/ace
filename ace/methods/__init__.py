from .baseline import baseline
from .dc import dc
from .ace import ace
from .tfgrpo import tfgrpo

METHODS = {m.name: m for m in [baseline, dc, ace, tfgrpo]}
