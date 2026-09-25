"""Готовые методы на новой архитектуре. Остальные (DC, SCOPE, TF-GRPO, EvoLib, MCE, хуки, гибриды) портируются:
их старый код — в коммите 2c5433e (git show 2c5433e:ace/methods/scope.py) и в теге pre-rewrite."""
from .ace import ace, ace_exact, ace_exact_dedup, ace_rewrite, ace_text
from .baseline import baseline

METHODS = {m.name: m for m in [baseline, ace, ace_text, ace_rewrite, ace_exact, ace_exact_dedup]}

# поток B: SCOPE, MCE, хуки, гибриды
from .scope import scope, scope_bo2, scope_code, scope_k2  # noqa: E402

METHODS.update({m.name: m for m in [scope, scope_bo2, scope_code, scope_k2]})
