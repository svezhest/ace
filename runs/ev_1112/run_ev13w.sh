#!/bin/bash
# EV13: правки 27B на входах набора, где их нет
cd /Users/user/Projects/nrhsi
bash probes/1111/series.sh runs/evset_1113 plain27t 1 1 2 -- 00 03 04 06 07 14
bash probes/1111/series.sh runs/evset_1113 think27 1 1 -- 00 03 04 06 07 14
echo "ALL done $(date +%H:%M)"
