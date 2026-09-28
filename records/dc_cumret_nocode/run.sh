#!/bin/bash
# запись DynamicCheatsheet_CumulativeRetrieval без исполнения кода. usage: run.sh OUT
exec "$(dirname "$0")/../dc_common/run.sh" "$1" --approach_name DynamicCheatsheet_CumulativeRetrieval \
    --cheatsheet_prompt_path prompts/curator_prompt_for_dc_cumulative.txt --execute_python_code
