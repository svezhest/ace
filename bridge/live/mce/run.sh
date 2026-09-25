#!/bin/sh
# Запись MCE: копия апстрима (git archive c4b7a7c) в ROOT, .venv — venv апстрима, окружение с нуля (env -i).
# До запуска: шлюз :8080, запись tools/record/record.py --seed на :8090, LiteLLM на :4000 (litellm.yaml) -> :8090.
# Пути ROOT фиксированы: они входят в промпты агентов (cwd, iter_dir) и воспроизведение строит тот же ROOT.
set -e
UP=${UPSTREAMS:-/Users/user/Projects/upstreams}
ROOT=/private/tmp/mce-live
HERE=$(cd "$(dirname "$0")" && pwd)
rm -rf "$ROOT"
mkdir -p "$ROOT/home" "$ROOT/tmp"
git -C "$UP/meta-context-engineering" archive c4b7a7c | tar -x -C "$ROOT"
ln -s "$UP/.venvs/mce" "$ROOT/.venv"
cp "$HERE/run.py" "$ROOT/run.py"
cd "$ROOT"
exec env -i $(cat "$HERE/env.txt" | sed "s#@ROOT@#$ROOT#g") "$ROOT/.venv/bin/python" run.py
