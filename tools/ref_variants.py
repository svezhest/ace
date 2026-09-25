"""Эталон вариантов ACE со старого кода под новыми именами методов:
    git worktree add /tmp/pre pre-rewrite
    uv run python tools/ref_variants.py /tmp/pre tools/ref_variants.json
База цепочки ace теперь — куратор операциями (curate_json), поэтому новый ace сравнивается со старым
swap(ace, curate=curate_json), ace_text — с тем же и рефлексией свободным текстом, ace_rewrite — с перезаписью.
baseline, ace_exact и ace_exact_dedup — те же, что в ref_trace.json."""
import runpy
import sys
from pathlib import Path

root, out = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)
from ace.loop import swap  # noqa: E402
from ace.methods import METHODS  # noqa: E402
from ace.methods.ace import ace, curate_json, curate_rewrite, reflect_text  # noqa: E402

METHODS["ace"] = swap(ace, "ace", curate=curate_json)
METHODS["ace_text"] = swap(ace, "ace_text", curate=curate_json, reflect=reflect_text)
METHODS["ace_rewrite"] = swap(ace, "ace_rewrite", curate=curate_rewrite)
sys.argv = ["trace.py", "--root", root, out, "baseline", "ace", "ace_text", "ace_rewrite", "ace_exact", "ace_exact_dedup"]
runpy.run_path(str(Path(__file__).parent / "trace.py"), run_name="__main__")
