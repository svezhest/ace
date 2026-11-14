"""EV19: оценщик промпта — пункт «без деталей задачи» и для примеров. Вход — итоговые src сессий EV15–EV17,
как в review.py (build_prompt_from, полный вид, наблюдение без заголовка); стенд plain27, один вызов на вход."""
import json, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "probes", "1112"))
import ev_input as EI  # noqa: E402
import ev_judge as EJ  # noqa: E402

OLD = "- the prompt stays general: it carries no details of the particular task from the observation (its names, values or the exact condition of that task)."
NEW = OLD[:-1] + ", not even as an example."
PROMPT = EI.PROMPTS["prompt_edit"]
assert PROMPT.count(OLD) == 1
VARIANT = os.environ.get("EV19", "a")
if VARIANT == "a":
    PROMPT = PROMPT.replace(OLD, NEW)
else:   # EV19b: пункт прежний; в форме ответа сначала выписать детали задачи из наблюдения, потом сверять строки
    FORM = "Answer in this form. First, one line for each new or changed passage"
    assert PROMPT.count(FORM) == 1
    PROMPT = PROMPT.replace(FORM, "Answer in this form. First, the details of the particular task from the observation: its names, "
                            "values and condition, one line each. Then one line for each new or changed passage")
VIEW = {"04": "app_r4", "05": "app_r4", "09": "app_n2", "14": "app_n2", "t4": "app_r1", "06": "alf_r1", "07": "alf_r4chk"}
INP = {"04": "04_v_rr", "05": "05_v_rr", "09": "09_v_rr", "14": "14_real", "t4": "t4", "06": "06_v_rr", "07": "07_v_rr"}
H, T, FULL = (os.path.join(ROOT, "runs", d) for d in ("evw_1113", "typed_1111", "full_1112"))
out = os.path.join(H, "ev19_plain27.jsonl" if VARIANT == "a" else f"ev19{VARIANT}_plain27.jsonl")
done = {json.loads(l)["tag"] for l in open(out)} if os.path.exists(out) else set()
prof = json.load(open(os.path.join(ROOT, "stands", "plain27.json")))
for tag in sys.argv[1:]:
    if tag in done:
        continue
    k = tag.split("_")[0]
    bench = "alf" if VIEW[k].startswith("alf") else "app"
    obs = re.sub(r"^Observation from a study of the agent's failed runs[^\n]*\n+", "", open(os.path.join(T, "in", INP[k] + ".txt")).read())
    final = EI.ES.read_src(os.path.join(H, "work", tag, "src"))
    user = EI.build_prompt_from(final, os.path.join(FULL, VIEW[k]), bench, obs)
    if not user:
        print(tag, "skip", flush=True)
        continue
    r = EJ.call(prof, PROMPT, user, 1)
    c = r["choices"][0]["message"].get("content") or ""
    v = EJ.parse(c)[0]
    open(out, "a").write(json.dumps({"tag": tag, "verdict": v, "content": c}, ensure_ascii=False) + "\n")
    print(tag, v, flush=True)
