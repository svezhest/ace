#!/bin/bash
# запись DC: подход default (без шпаргалки), код исполняется. usage: run.sh OUT
exec "$(dirname "$0")/../dc_common/run.sh" "$1" --approach_name default
