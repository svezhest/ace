"""Показ TF-GRPO: вся библиотека опытов в инструкции итогового агента: «When solving problems, you MUST first
carefully read ...», «[G0]. опыт»."""
from .. import prompts, render
from . import Whole

EXPERIENCES = Whole(layout=lambda recs, memory: render.experiences(recs), head="",
                    before=prompts.text("tfgrpo_experiences_intro"))
