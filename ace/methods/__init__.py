from .baseline import baseline
from .dc import dc
from .ace import ace
from .tfgrpo import tfgrpo
from .scope import scope
from .evolib import evolib
from .mce import mce
from .proto import proto

METHODS = {m.name: m for m in [baseline, dc, ace, tfgrpo, scope, evolib, mce, proto]}
