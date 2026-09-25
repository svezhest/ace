"""Готовые методы на новой архитектуре. Остальные (SCOPE, MCE, хуки, гибриды) портируются:
их старый код — в коммите 2c5433e (git show 2c5433e:ace/methods/scope.py) и в теге pre-rewrite."""
from .ace import ace, ace_exact, ace_exact_dedup, ace_rewrite, ace_text
from .baseline import baseline
from .dc import dc, dc_code, dc_history, dc_retrieval, dc_rs
from .evolib import evolib, evolib_judge
from .tfgrpo import tfgrpo

METHODS = {m.name: m for m in [baseline, ace, ace_text, ace_rewrite, ace_exact, ace_exact_dedup,
                                  dc, dc_code, dc_rs, dc_retrieval, dc_history, tfgrpo, evolib, evolib_judge]}
