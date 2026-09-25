"""Реестр методов: имя -> ученик (или обёртка над ним)."""
from .ace import ace, ace_dedup, ace_stand, ace_stand_rewrite, ace_stand_text, ace_used
from .baseline import baseline
from .dc import dc, dc_code, dc_history, dc_retrieval, dc_rs
from .evolib import evolib, evolib_judge
from .hybrids import ace_stand_bo2, ace_stand_group, ace_stand_hooks, ace_stand_opt
from .mce import mce, mce_ace_stand, mce_fs
from .scope import scope, scope_bo2, scope_code, scope_k2
from .tfgrpo import tfgrpo

METHODS = {m.name: m for m in [baseline, ace, ace_used, ace_dedup, ace_stand, ace_stand_text, ace_stand_rewrite, dc,
                               dc_code, dc_rs, dc_retrieval, dc_history, tfgrpo, evolib, evolib_judge, scope, scope_bo2,
                               scope_code, scope_k2, mce, mce_fs, mce_ace_stand, ace_stand_bo2, ace_stand_opt,
                               ace_stand_hooks, ace_stand_group]}
