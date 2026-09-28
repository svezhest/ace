#!/bin/bash
# запись Dynamic_Retrieval без исполнения кода. usage: run.sh OUT
exec "$(dirname "$0")/../dc_common/run.sh" "$1" --approach_name Dynamic_Retrieval --execute_python_code
