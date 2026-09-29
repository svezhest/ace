#!/bin/sh
# Окружения для снятия эталонов после git clone --recursive. Апстримы — подмодули upstreams/ на закреплённых
# коммитах; производное (venv, данные, кэши HF и tiktoken) — рядом с ними: upstreams/.venvs, .data, .hf, .hf-evolib,
# .tiktoken (под .gitignore). UPSTREAMS — другой каталог апстримов с тем же устройством.
# usage: records/setup_envs.sh [ace|mce|youtu|gepa|light|dc|evolib|litellm ...]   (без аргументов — все)
set -e
ACE=$(cd "$(dirname "$0")/.." && pwd)
UP=${UPSTREAMS:-$ACE/upstreams}
V=$UP/.venvs
mkdir -p "$V" "$UP/.tiktoken" "$UP/.data"

# апстримы — на коммитах, закреплённых в репозитории, без правок
[ -n "${UPSTREAMS:-}" ] || git -C "$ACE" submodule update --init
git -C "$ACE" ls-files -s upstreams/ | while read -r _ commit _ path; do
  name=${path#upstreams/}
  [ "$(git -C "$UP/$name" rev-parse HEAD)" = "$commit" ] || { echo "$UP/$name не на $commit" >&2; exit 1; }
  [ -z "$(git -C "$UP/$name" status --porcelain)" ] || { echo "$UP/$name: дерево грязное" >&2; exit 1; }
done

# venv стенда: прокси записи и сервер эмбеддингов
(cd "$ACE" && uv sync -q)

# кэш tiktoken (в контейнерах без сети): имя файла — sha1 адреса, как у самого tiktoken
for enc in cl100k_base o200k_base; do
  url=https://openaipublic.blob.core.windows.net/encodings/$enc.tiktoken
  f=$UP/.tiktoken/$(printf %s "$url" | shasum | cut -c1-40)
  [ -s "$f" ] || curl -fsSL -o "$f" "$url"
done

# зависимости из uv.lock апстрима, сам проект не ставим (иначе в дереве подмодуля появятся egg-info)
locked() {  # venv project python [аргументы uv export: --extra ...]
  venv=$1 project=$2 python=$3
  shift 3
  uv venv -q --allow-existing -p "$python" "$V/$venv"
  uv export -q --frozen --no-hashes --no-emit-project --project "$UP/$project" "$@" > "$V/$venv.req.txt"
  uv pip install -q -p "$V/$venv" --index-url https://pypi.org/simple -r "$V/$venv.req.txt"
}

want() { [ -z "$ARGS" ] || echo " $ARGS " | grep -q " $1 "; }
ARGS="$*"

want ace && locked ace ace 3.11
want mce && locked mce meta-context-engineering 3.11
if want youtu; then
  locked youtu youtu-agent 3.12
  # данные records/tfgrpo: parquet DAPO-Math-17k (prep.py кладёт его туда, куда качает апстрим) и AIME24 в кэше HF
  f=$UP/.data/DAPO-Math-17k/data/dapo-math-17k.parquet
  mkdir -p "$(dirname "$f")"
  [ -s "$f" ] || curl -fsSL -o "$f" \
    https://huggingface.co/datasets/BytedTsinghua-SIA/DAPO-Math-17k/resolve/main/data/dapo-math-17k.parquet
  echo "534375d6bb8630d22ab46a56e11f2ffec1d288d8f7d04099bc82d68948705941  $f" | shasum -a 256 -c -s
  HF_HOME=$UP/.hf "$V/youtu/bin/python" -c "
from datasets import load_dataset
load_dataset('HuggingFaceH4/aime_2024', split='train')" >/dev/null
fi
if want gepa; then
  locked gepa gepa 3.12 --extra full
  # наборы квикстарта (records/gepa_quickstart) — его же init_dataset в кэш HF
  HF_HOME=$UP/.hf PYTHONPATH=$UP/gepa/src PYTHONDONTWRITEBYTECODE=1 "$V/gepa/bin/python" -c "
import gepa
gepa.examples.aime.init_dataset()" >/dev/null
fi
if want light; then
  # SCOPE + DC + EvoLib: у DC и EvoLib нет lock-файла, ставим по импортам
  uv venv -q --allow-existing -p 3.11 "$V/light"
  uv pip install -q -p "$V/light" -r "$UP/EvoLib/EvoLib/requirements.txt" \
    "openai>=1.0.0" "anthropic>=0.18.0" "litellm>=1.0.0" python-dotenv \
    numpy tiktoken scikit-learn
fi
# образ записей DC (records/dc_*); youtu-upstream и mce-upstream раннеры собирают сами
want dc && docker build -q -t dc-upstream "$ACE/records/dc_code_v2" >/dev/null
# EvoLib (records/evolib, records/evolib_hmmt): образ evolib-upstream, исходники lcb_runner и грейдера matharena
# монтируются в контейнер; кэш HF для записей — $UP/.hf-evolib (LiveCodeBench v6: скрипт датасета качает все
# test*.jsonl, ~4,2 ГБ; три набора HMMT); BGE-M3 для tools/record/embeddings — в $UP/.hf
if want evolib; then
  docker build -q -t evolib-upstream "$ACE/records/evolib" >/dev/null
  mkdir -p "$UP/.hf-evolib"
  docker run --rm -v "$UP/.hf-evolib":/hf -v "$UP/LiveCodeBench":/lcb:ro -w /lcb -e HF_HOME=/hf -e PYTHONPATH=/lcb \
    -e PYTHONDONTWRITEBYTECODE=1 evolib-upstream python -c "
from datasets import load_dataset
from lcb_runner.benchmarks import load_code_generation_dataset
load_code_generation_dataset(release_version='v6')
for name in ['hmmt_feb_2025', 'hmmt_nov_2025', 'hmmt_feb_2026']:
    load_dataset(f'MathArena/{name}', split='train')" >/dev/null
  (cd "$ACE" && HF_HOME=$UP/.hf .venv/bin/python -c "from tools.record.embeddings import model; model()")
fi
# LiteLLM proxy для агентов Claude SDK в MCE (запись records/mce_symptom)
if want litellm; then
  uv venv -q --allow-existing -p 3.12 "$V/litellm"
  uv pip install -q -p "$V/litellm" --index-url https://pypi.org/simple "litellm[proxy]==1.102.1"
fi
echo ok
