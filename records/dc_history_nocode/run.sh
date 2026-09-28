#!/bin/bash
# запись FullHistoryAppending без исполнения кода. usage: run.sh OUT
exec "$(dirname "$0")/../dc_common/run.sh" "$1" --approach_name FullHistoryAppending --execute_python_code
