"""Методы на новой архитектуре. ace_group (контраст TF-GRPO в ACE) ещё не перенесён: старый код — в теге
pre-rewrite (git show pre-rewrite:ace/methods/hybrids.py)."""
from .ace import ace, ace_exact, ace_exact_dedup, ace_rewrite, ace_text
from .baseline import baseline
from .dc import dc, dc_code, dc_history, dc_retrieval, dc_rs
from .evolib import evolib, evolib_judge
from .tfgrpo import tfgrpo

METHODS = {m.name: m for m in [baseline, ace, ace_text, ace_rewrite, ace_exact, ace_exact_dedup,
                                  dc, dc_code, dc_rs, dc_retrieval, dc_history, tfgrpo, evolib, evolib_judge]}

# поток B: SCOPE, MCE, хуки, гибриды
from .hybrids import ace_bo2, ace_hooks, ace_opt  # noqa: E402
from .mce import mce, mce_ace  # noqa: E402
from .scope import scope, scope_bo2, scope_code, scope_k2  # noqa: E402

METHODS.update({m.name: m for m in [scope, scope_bo2, scope_code, scope_k2, mce, mce_ace, ace_bo2, ace_opt, ace_hooks]})
