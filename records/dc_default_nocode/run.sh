#!/bin/bash
# запись DC: подход default без исполнения кода. usage: run.sh OUT
exec "$(dirname "$0")/../dc_common/run.sh" "$1" --approach_name default --execute_python_code
