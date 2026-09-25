#!/bin/sh
# Окружения для снятия эталонов: чистые worktree апстримов на зафиксированных коммитах и venv через uv.
# usage: bridge/setup_envs.sh [ace|mce|youtu|light|litellm ...]   (без аргументов — все)
set -e
UP=${UPSTREAMS:-$HOME/Projects/upstreams}
V=$UP/.venvs
mkdir -p "$V"

tree() {  # name commit
  [ -d "$UP/$1" ] || git -C "${REPRO:?REPRO — папка с git-клонами апстримов}/$1" worktree add --detach "$UP/$1" "$2"
  test "$(git -C "$UP/$1" rev-parse --short=7 HEAD)" = "$2"
}
tree ace 82709de
tree dynamic-cheatsheet 5cfe3c3
tree SCOPE 4dc0da5
tree EvoLib 98266b2
tree meta-context-engineering c4b7a7c
tree youtu-agent c2caa53

# зависимости из uv.lock апстрима, сам проект не ставим (иначе в worktree появятся egg-info)
locked() {  # venv project python [extra index args]
  uv venv -q --allow-existing -p "$3" "$V/$1"
  uv export -q --frozen --no-hashes --no-emit-project --project "$UP/$2" > "$V/$1.req.txt"
  uv pip install -q -p "$V/$1" --index-url https://pypi.org/simple -r "$V/$1.req.txt"
}

want() { [ -z "$ARGS" ] || echo " $ARGS " | grep -q " $1 "; }
ARGS="$*"

want ace && locked ace ace 3.11
want mce && locked mce meta-context-engineering 3.11
want youtu && locked youtu youtu-agent 3.12
if want light; then
  # SCOPE + DC + EvoLib: у DC и EvoLib нет lock-файла, ставим по импортам
  uv venv -q --allow-existing -p 3.11 "$V/light"
  uv pip install -q -p "$V/light" -r "$UP/EvoLib/EvoLib/requirements.txt" \
    "openai>=1.0.0" "anthropic>=0.18.0" "litellm>=1.0.0" python-dotenv \
    numpy tiktoken scikit-learn
fi
# LiteLLM proxy для агентов Claude SDK в MCE (запись bridge/live/mce и её воспроизведение в tests/live/test_mce.py)
if want litellm; then
  uv venv -q --allow-existing -p 3.12 "$V/litellm"
  uv pip install -q -p "$V/litellm" --index-url https://pypi.org/simple "litellm[proxy]==1.102.1"
fi
echo ok
