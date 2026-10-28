# wait until any supervisor log (logs/r4*_sup.log) gets a new "stopped", "done" or "SUP_GIVEUP" line; print and exit
cd "$(dirname "$0")"
declare -A seen
for f in logs/r4*_sup.log; do seen[$f]=$(grep -c -E "stopped|done|SUP_GIVEUP" "$f"); done
while true; do
  sleep 20
  for f in logs/r4*_sup.log; do
    n=$(grep -c -E "stopped|done|SUP_GIVEUP" "$f")
    if [ "$n" != "${seen[$f]:-0}" ]; then echo "== $f"; tail -4 "$f"; exit 0; fi
  done
done
