#!/usr/bin/env bash
# run10.sh
set -euo pipefail

rm -f results.txt

for i in {1..10}; do
  echo "=== RUN $i ===" | tee -a results.txt

  docker rm -f ecs152a-simulator >/dev/null 2>&1 || true
  rm -f hdd/file2.mp3

  ./start-simulator.sh > "simlog_${i}.txt" 2>&1 &
  SIM_PID=$!

  sleep 2

  # stdout -> results.txt, stderr (progress) shows on screen
  python3 sender_stop_and_wait_Xiang_Mao_and_.py | tee -a results.txt

  docker rm -f ecs152a-simulator >/dev/null 2>&1 || true
  kill "$SIM_PID" >/dev/null 2>&1 || true
done

python3 - << 'PY'
import re

nums = []
with open("results.txt", "r", encoding="utf-8", errors="ignore") as f:
    for ln in f:
        s = ln.strip()
        if not s or s.startswith("==="):
            continue
        if re.fullmatch(r"[-+]?\d+(\.\d+)?", s):
            nums.append(float(s))

if len(nums) != 30:
    raise SystemExit(f"Expected exactly 30 numbers (10 runs * 3 lines), got {len(nums)}. Check results.txt.")

thr = nums[0::3]
dly = nums[1::3]
met = nums[2::3]

thr_avg = sum(thr) / 10
dly_avg = sum(dly) / 10
met_avg = sum(met) / 10

print("=== AVERAGES OVER 10 RUNS ===")
print(f"{thr_avg:.7f}")
print(f"{dly_avg:.7f}")
print(f"{met_avg:.7f}")
PY
