from .baseline import baseline
from .dc import dc, dc_rs
from .ace import ace
from .tfgrpo import tfgrpo
from .scope import scope, scope_k2
from .evolib import evolib
from .mce import mce
from .proto import proto

from .hybrids import HYBRIDS

METHODS = {m.name: m for m in HYBRIDS + [baseline, dc, dc_rs, ace, tfgrpo, scope, scope_k2, evolib, mce, proto]}
