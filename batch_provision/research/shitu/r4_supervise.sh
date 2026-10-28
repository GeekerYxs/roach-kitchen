# Round 4 supervisor for one team: r4_sup.sh TEAM [MID_FROM|early|late] [LATE_FROM]   (early = r4_early.sh first)
# Runs r4_mid.sh then r4_late.sh (via r4_run.sh, logs appended to logs/r4<TEAM>_<script>.log). When a run stops
# without its *_DONE line, it reads the last "== STEP <name>" marker, cleans up (everybody cancels the path-finder
# and leaves the team) and restarts from that step; the same step at most 3 times, then it gives up
# ("SUP_GIVEUP <script> <step>" in logs/<LOGID>_sup.log; r4_line.py then tries its own recovery).
# Before every run: game windows (r4_util windows: lost apprentice -> logged in again, lost master -> SUP_GIVEUP
# MASTER_DOWN). During a run: a log silent for SILENT (900) s = hung -> the run's process tree is killed (= a stop).
cd "$(dirname "$0")"
{   # parsed whole before it runs: editing this file cannot shift a running supervisor
T=$1
. ./r4_env.sh "$T"; SUPLOG=logs/${LOGID}_sup.log
SILENT=${SILENT:-900}   # a run whose log stays unchanged this many seconds is hung: kill it, it counts as a stop
killtree() {   # killtree PID: PID and all its descendants (MSYS ps lists the Windows python children too)
  local k
  for k in $(ps -ef | awk -v p="$1" '$3==p{print $2}'); do killtree "$k"; done
  kill "$1" 2>/dev/null
}
watch_run() {  # watch_run PID LOG: wait for PID; kill its tree when LOG has not changed for SILENT s
  local pid=$1 log=$2 now m
  while kill -0 "$pid" 2>/dev/null; do
    sleep 30
    now=$(date +%s); m=$(stat -c %Y "$log" 2>/dev/null || echo "$now")
    if [ $((now - m)) -ge "$SILENT" ]; then
      echo "$(date +%H:%M:%S) HANG: $log silent $((now - m)) s, killing the run" >> "$SUPLOG"
      echo "$(date +%H:%M:%S.000) 停止: 日志 $((now - m)) 秒没有变化，判定卡死" >> "$log"
      killtree "$pid"
    fi
  done
  wait "$pid" 2>/dev/null
}
run() {   # run SCRIPT FROM TAG
  local S=$1 from=$2 tag=$3 log=logs/${LOGID}_${1%.sh}.log
  declare -A tries
  while true; do
    # windows first: a lost apprentice is logged in again; a lost master stops the team (MASTER_DOWN)
    python -X utf8 r4_util.py windows $PAIRS >> "$SUPLOG" 2>&1
    case $? in 0) ;; 2) echo "$(date +%H:%M:%S) SUP_GIVEUP $S MASTER_DOWN" >> "$SUPLOG"; return 1 ;;
      *) echo "$(date +%H:%M:%S) 窗口检查失败，60 秒后再试" >> "$SUPLOG"; sleep 60; continue ;; esac
    echo "$(date +%H:%M:%S) start $S FROM=$from" >> "$SUPLOG"
    touch "$log"
    FROM=$from bash r4_run.sh "$T" "$S" >> "$SUPLOG" 2>&1 &
    watch_run $! "$log"
    if tail -3 "$log" | grep -q "$tag"; then
      echo "$(date +%H:%M:%S) done $S" >> "$SUPLOG"; return 0
    fi
    last=$(grep "^== STEP " "$log" | tail -1 | awk '{print $3}')
    last=${last:-$from}
    tries[$last]=$(( ${tries[$last]:-0} + 1 ))
    echo "$(date +%H:%M:%S) $S stopped in step $last (try ${tries[$last]}): $(grep -E '停止:|Error|Stop' "$log" | tail -1 | cut -c1-200)" >> "$SUPLOG"
    if [ "${tries[$last]}" -gt 3 ]; then
      echo "$(date +%H:%M:%S) SUP_GIVEUP $S $last" >> "$SUPLOG"; return 1
    fi
    # r4_late's steps start from 逍遥村 (pp_chain needs a PP鸡 map): scroll home; r4_mid's from where the team stands
    if [ "$S" = r4_late.sh ]; then cmd=home; else cmd=leave; fi
    ( python -X utf8 r4_util.py $cmd ) >> "$SUPLOG" 2>&1
    sleep 5
    from=$last
  done
}
if [ "${2:-start}" = late ]; then      # r4_sup.sh T late STEP: r4_late.sh only, from STEP
  run r4_late.sh "${3:-q181}" R4_LATE_DONE
elif [ "${2:-start}" = early ]; then
  run r4_early.sh start R4_EARLY_DONE && run r4_mid.sh start R4_MID_DONE && run r4_late.sh q181 R4_LATE_DONE
else
  run r4_mid.sh "${2:-start}" R4_MID_DONE && run r4_late.sh "${3:-q181}" R4_LATE_DONE
fi
exit
}
