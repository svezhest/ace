import gepa

trainset, valset, _ = gepa.examples.aime.init_dataset()

seed_prompt = {
    "system_prompt": "You are a helpful assistant. Answer the question. "
                     "Put your final answer in the format '### <answer>'"
}

result = gepa.optimize(
    seed_candidate=seed_prompt,
    trainset=trainset,
    valset=valset,
    task_lm="openai/ornith15-9b",
    max_metric_calls=150,
    reflection_lm="openai/ornith15-9b",
)

print("Optimized prompt:", result.best_candidate['system_prompt'])
