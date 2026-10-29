"""splits.json from AppWorld's dataset files. test_normal / test_challenge are not listed: never run."""
import json
from pathlib import Path

D = Path.home() / "Projects/appworld/data/datasets"
ids = lambda name: [l.strip() for l in (D / f"{name}.txt").read_text().splitlines() if l.strip()]
train, val = ids("train"), ids("dev")
assert not set(train) & set(val)
for name in ("test_normal", "test_challenge"):
    assert not (set(train) | set(val)) & set(ids(name))
out = {"_note": "train = AppWorld train (material: random tasks); val = AppWorld dev; "
                 "test_normal and test_challenge are not used at all (not listed, runner has no test split).",
       "train": train, "val": val}
Path(__file__).resolve().parents[1].joinpath("splits.json").write_text(json.dumps(out, indent=0) + "\n")
print(len(train), len(val))
