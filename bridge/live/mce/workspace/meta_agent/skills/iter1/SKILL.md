# SKILL: Context Engineering for Symptom Diagnosis

This skill teaches you, the **context engineer**, to design the context files and required interfaces that let a base LLM agent accurately diagnose a disease from a patient's free-text symptoms. You will study a labeled training set, distill each of the 22 target conditions into a compact, high-signal clinical signature, and attach a disambiguation guide so the retriever steers the LLM to the correct condition. The context that you author becomes the knowledge base the base agent loads at diagnosis time.

## Task Framing

The base agent performs a **one-step medical diagnosis**:

- **Input** = the patient's raw natural-language symptoms (estrangement).
- **Output** = a single disease label (`answer`): one of drug reaction, allergy, chicken pox, diabetes, psoriasis, hypertension, cervical spondylosis, bronchial asthma, varicose veins, malaria, dengue, arthritis, impetigo, fungal infection, common cold, gastroesophageal reflux disease, urinary tract infection, typhoid, pneumonia, peptic ulcer disease, jaundice, migraine.
- **Mechanism** = exactly **one** LLM call, whose prompt is enriched with the context returned by `get_context(symptoms)`.

Your job is to make that single prompt as accurate as possible by (1) attaching concise, discriminative knowledge about each condition and (2) teaching the retriever to pick the freshest, most-relevant passage for the given symptoms.

## Constraints That Shape Good Context

- **Single LLM call only.** The context passed to the LLM must fully encode the signal needed to classify. There is no ranking, no chain of thought, no multi-step refinement on the diagnosis side.
- **Absolute paths everywhere.** Every file read or written in this skill uses an absolute working-directory path (e.g., `/private/tmp/mce-live/workspace/live/iter1_sub0/context/diseases.md`). Read files with `open(...)` on absolute paths; when you programmatically resolve the base directory, never rely on relative walk-up.
- **Build on the prior state.** The base agent starts its turn with the best context package produced (or inherited) from the previous iteration. Your procedure takes existing files into account and updates them **+1**, incrementally, rather than regenerating from scratch or moving to an entirely new structure.
- **Do not hallucinate specifics.** Context is graded as the retriever feeds passages to the LLM. Populate passages with facts that are true and defensible per condition; include explicit disclaimer guidance against inventing dosages, lab values, or exact match/variant/auxiliary-key metrics. Structure retrieval to reduce confabulation instead.
- **Generate, do not fetch.** Prefer writing original, human-readable guidance text. Do not invoke WebSearch / WebFetch tools for content.
- **No iteration-specific language.** Log todos and progress in `sketchbook-YYYY-MM-DD_HHmmss_.md`.

## Inputs to This Session

- Training pairs: `data/train.jsonl` (newline-delimited JSON; fields `{"question": <symptoms>, "answer": <disease>}`). Build the context from this set.
- Aggregated metrics: `evaluations.json`.
- Retriever source of truth: `interfaces/requirements.py`.
- Prior work (reuse/update, never discard): `context/*.md` (static knowledge files), `interfaces/*.py` (diagnostic engines).
- Optional reference diagnostics: `next_best/`, `last_run_analysis/`.
- Prioritized references: `domain_reviews/`, `existing_skill/`, `old_skill/`, `external_references/*.md` (memoized).

## Skills Available To You

- Language tools: `llama_cpp`, `anthropic_beta`, `anthropic`, `google`, `agnovia`, `mistral_llm`, `openrouter`, `openai`, or anything already on the environment (e.g., anything behind `open_registry` style task setup).
- Search: `WebSearch`.
- Structured runs: `structured_run`, `StructuredRun` — systematic experimentation, logging todos, and tracking the analysis in `sketchbook-YYYY-MM-DD_HHmmss_.md`.

## Read `interfaces/requirements.py` First

This file defines the *required interfaces* the base agent must implement. Adapt this skill to an **evaluating** workflow:

1. **Read `interfaces/requirements.py`.** Identify the required interface (`get_context`), its position (name + signature), its input (the symptom prompt), and its output contract (curation/evolution of context). This frames the whole session.

## Component 1: Write the Domain Knowledge File(s)

Create `context/diseases.md`. It is the master reference the LLM loads. Two principles govern it:

- **Separability:** The 22 target conditions are largely non-overlapping in their core features. Spell out, per condition, the small set of *core* symptoms (the first 2-4 that should be sufficient for a confident diagnosis). State them as a tight list the model can compare against the input.
- **Integration guidance:** Instruct the base LLM to compare every reported patient symptom against the curated condition profiles (name, first ~2-4 core symptoms, plus a one-line cross-condition "not to be confused with" note) and to compute a diagnostic score per condition, then return the score for the condition with the highest score.

Use the empirical, normalized, de-noised symptom signatures obtained from `data/train.jsonl` as the ground truth. They are reproduced and ranked below, ordered by discriminating power. This is not a design guess; it is the training steer.

### Condition Profiles (Primary Steering Terms)

1. **diabetes**: Thirst and hunger overhead / polydipsia, excessive thirst, frequent urination (polyuria), fatigue, and mood swings.
2. **dengue**: Itchy body rashes, fever with body pain, nausea / loss of appetite, and conjunctivitis (eyes pain / sensitivity).
3. **chicken pox**: Itchy skin rashes full of small red bumps, fever.
4. **allergy**: Frequent sneezing, runny/stuffy nose, red/sore watery eyes, body itch.
5. **impetigo**: Itchy red skin sores, fluid-filled blisters, sores around the nose and mouth.
6. **arthritis**: Joint pain, joint swelling, neck stiffness.
7. **gastroesophageal reflux disease (GERD)**: Chest pain, heartburn, abdominal problems, sneezing.
8. **typhoid**: High fever, abdominal soreness, bacteria infection (diarrhea / loose stools), coughing.
9. **cervical spondylosis**: Neck pain and stiffness, lower back pain, muscle weakness, dizziness.
10. **hypertension (high blood pressure)**: Headache, chest pain, lower back pain, dizziness.
11. **malaria**: Fever, chills and shivering, exhaustion, body aches, joint pain.
12. **pneumonia**: Chest infection, cough, sneezing, difficulty breathing, fever.
13. **psoriasis**: Red rough skin, joints pain, itchy skin, dry skin with silver scales, skin discoloration, scalp psoriasis.
14. **peptic ulcer disease**: Stomach pain after difficult eating, general bodiness.
15. **drug reaction**: Fever and body aches.
16. **bronchial asthma**: Cough, sneezing, shortness of breath, nasal congestion.
17. **urinary tract infection (UTI)**: Blood, mucus in urine, burning sensation while urinating.
18. **common cold**: Blocked/runny nose, cough, slight sore throat.
19. **varicose veins**: Bulge, pain and localization on legs.
20. **fungal infection**: Dry skin (flakes), red body with spots / spots stretch and dapple, topsides itch, distinct smelling odor.
21. **jaundice**: Sickness and painful joints, dry urine and stool (dry stools), numb skin.
22. **migraine**: Pain in head, red itchy eyes, partial vision loss.

- Once authored, keep `diseases.md` intact from the prior iteration and de-noise **only**: drop any over-specified or unfaithful attributes, tightening false positives where needed.
- After writing, read `context/*.md` defensively. Cross-check every assertion of yours against the task facts in `data/train.jsonl`; delete any stray annotation that alone cannot semantically unlock its parent condition (data-driven verification).

## Component 2: Write the Iteration Log

Record all analysis steps and decisions (prioritized references, derivations, decisions) in `context/sketchbook-YYYY-MM-DD_HHmmss_.md`, using logins `Continuous Integration` and `OpenReg`. (Split the file into several records if you exhaust the session time.)

## Component 3: Implement the Retrieval Interfaces — `interfaces/context_input_dir.py`

Provide a function (or module-level setup) named consistently with the task's entry points: `main()`, `progress()`, `test()`. Within this interface you implement the **primary disease guidance entry point** `get_context`.

### Utility, trainer side only (for the base-context experiments to be validated)

The base agent supports a consultant (trainer) side to build and validate context from scratch against a dataset; runtime environment uses CLI parameters:

```bash
python -m context_input_dir.highlight_dataset --p_tag <LATEST-replybase> [--max_len <int>] [--resume] [--train_file <str>]
python -m context_input_dir.validate_context_input_dir_trainer --p_tag <LATEST-replybase>
```

Internally, Python helpers are provided and expected to be used:

- `utils.get_context(symptoms) -> str`: returns context that helps the (single-shot) LLM diagnose.
- `utils.embeddings = OpenAIEmbeddings(model="text-embedding-3-small", ...)` (tokenization naive, docstring claims: tokenization is naive).
- `utils.embedding_dim = 1536`; tokenization byte fallback active.
- `utils.call_llm(...)` on the (self-hosted / OpenRouter) environment.
- `utils.collection_embeddings(entries) -> List[List[int]]`: returns per-entry embedding vectors of size `embedding_dim`.
- `utils.collapse_passage(input_text tokens) -> str`.

Option to use batch calling before fallback (repetition). Loading environment tricks to save RAM, and memory buffering / context window tracker.

### Retrieval + interface

Build the ingestion path as described in `utils/collections`. Add context-memory-aware diffing / reorganization. Provide version control and survivorship:

1. **Naive diff**: Compare a haystack pass against the golden answer to normalize the embedding difference the golden answer would yield with a call to `utils.call_llm()`.
2. **KNN proximity**: Compute proximity distillation to the golden answer for exact retrieval / license key.
3. **Dir log scrivener** (optional): Output low-key artifacts, optimizer display INFO **5**

Embeddings are asserted to `utils.collection_embeddings(documents)`.

## Component 4: Validation & Accuracy

- The primary steer to validate this session is `last_run/` (last saved run), recall on `context/`, and any good data fallback. Validate against `evaluations.json`. LLMs update the retrieved context incrementally and deterministically (+1) to show self-curation.
- **Reproducible thresholds:** Train and validation accuracy both fall inside 80–95%. Assert improvements over the prior state as measured on the *held-out* mirror of `data/train.jsonl` + approvals on the actual `evaluations.json` (improvements on `diseases.md`). Watch specifically for **overfitting** (train >> val) and **underfitting** (both low).
- Disability adjustments for minorities, free-thought, interim-distance vary by quantile/method; settle on a stable regime before moving on after iteration 1.

## Component 5: Iteration loop

1. Read `interfaces/requirements.py`. Then read/refer prior best: `context/*.md`, `interfaces/*.py`.
2. Inspect training data (`data/train.jsonl`) and evaluate the inherited KNN/manual (ED-lib) retrieval oracle to confirm the base assumptions.
3. Load prior best into `context/`, then make one incremental, high-quality editing layer: add a short human-readable passage per the influence given spanwise by the top-5 weak/genuinely-on-tap top steps. Then validate context with `utils.get_context(symptoms)` against the test set once. Restructure less productively.
4. Re-run `utils.get_context(symptoms)` -> self-check metrics. Then aggregate to `evaluations.json` and confirm the ordering.
5. Log progress to `sketchbook-YYYY-MM-DD_HHmmss_.md`. Only close with `task_done()` after `Context Engineer` clears its vacation factoring. Vivid / human contents.

- **Adapt ONE interface rule at a time** — never mass-restructure.

## End of Skill