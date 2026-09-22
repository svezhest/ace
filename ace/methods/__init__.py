from .baseline import baseline
from .dc import dc, dc_code, dc_history, dc_retrieval, dc_rs
from .ace import ace, ace_exact, ace_exact_dedup
from .tfgrpo import tfgrpo
from .scope import scope, scope_bo2, scope_k2
from .evolib import evolib, evolib_judge
from .mce import mce
from .proto import proto

from .hybrids import HYBRIDS

METHODS = {m.name: m for m in HYBRIDS + [baseline, dc, dc_code, dc_rs, dc_retrieval, dc_history, ace, ace_exact, ace_exact_dedup, tfgrpo, scope, scope_bo2, scope_k2, evolib, evolib_judge, mce, proto]}
