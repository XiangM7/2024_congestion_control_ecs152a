#!/usr/bin/env bash
set -euo pipefail

rm -f results.txt

for i in {1..10}; do
  echo "=== RUN $i ===" | tee -a results.txt

  docker rm -f ecs152a-simulator >/dev/null 2>&1 || true
  rm -f hdd/file2.mp3

  ./start-simulator.sh > "simlog_${i}.txt" 2>&1 &
  SIM_PID=$!

  sleep 2

  DEBUG=1 python3 sender_stop_and_wait_Xiang_Mao_and_.py | tee -a results.txt

  docker rm -f ecs152a-simulator >/dev/null 2>&1 || true
  kill "$SIM_PID" >/dev/null 2>&1 || true
done
