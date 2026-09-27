#!/bin/bash
# запись Dynamic_Retrieval с исполнением кода: общий раннер ../dc_code_v2/run.sh. usage: run.sh OUT
exec "$(dirname "$0")/../dc_code_v2/run.sh" "$1" Dynamic_Retrieval ""
