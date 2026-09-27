#!/bin/bash
# запись DC-RS с исполнением кода: общий раннер ../dc_code_v2/run.sh. usage: run.sh OUT
exec "$(dirname "$0")/../dc_code_v2/run.sh" "$1" DynamicCheatsheet_RetrievalSynthesis \
    prompts/curator_prompt_for_dc_retrieval_synthesis.txt
