# exit when any team's r4_late log has gone LIMIT minutes (default 30) without a new "== STEP" line while its
# supervisor is still running it (2026-10-28: team B walked 35 min in the 古迹, team D patrolled 44 min for kills
# already done; neither run stopped, so r4_watch.sh never fired). Prints the team and its last lines.
cd "$(dirname "$0")"
{
LIMIT=${1:-30}
while true; do
  sleep 60
  now=$(date +%s)
  for f in logs/r4?_r4_late.log logs/r4?_b?_r4_late.log; do
    [ -f "$f" ] || continue
    sup=${f%_r4_late.log}_sup.log
    tail -1 "$sup" | grep -q -E "done r4_late|SUP_GIVEUP|stopped by hand" && continue
    last=$(grep "^== STEP " "$f" | tail -1 | awk '{print $4}')
    [ -n "$last" ] || continue
    t=$(date -d "$(date +%F) $last" +%s 2>/dev/null) || continue
    [ $t -gt $now ] && t=$((t - 86400))
    if [ $(( (now - t) / 60 )) -ge "$LIMIT" ] && [ $(( (now - $(stat -c %Y "$f")) / 60 )) -lt 5 ]; then
      echo "== $f: step $(grep '^== STEP ' "$f" | tail -1) for $(( (now - t) / 60 )) min"; tail -4 "$f"; exit 0
    fi
  done
done
exit
}
