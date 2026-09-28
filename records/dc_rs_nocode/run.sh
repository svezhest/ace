#!/bin/bash
# запись DC-RS без исполнения кода. usage: run.sh OUT
exec "$(dirname "$0")/../dc_common/run.sh" "$1" --approach_name DynamicCheatsheet_RetrievalSynthesis \
    --cheatsheet_prompt_path prompts/curator_prompt_for_dc_retrieval_synthesis.txt --execute_python_code
