#!/bin/bash
# запись DC: DynamicCheatsheet_CumulativeRetrieval, код исполняется. usage: run.sh OUT
exec "$(dirname "$0")/../dc_common/run.sh" "$1" --approach_name DynamicCheatsheet_CumulativeRetrieval \
    --cheatsheet_prompt_path prompts/curator_prompt_for_dc_cumulative.txt
