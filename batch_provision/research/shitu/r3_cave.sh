# Round 3, one team at 通天塔 30: task 224 for the apprentices (each alone, in parallel), master to 无尽2路口,
# team into 遗忘洞穴, the master gathers 9 花 + 3 石 (casting itself). The snake (dts.py) is run separately: its first
# 「开打」 brings a 0x46f5 quiz the user answers by hand.
# Env: SHITU_STATE, SHITU_MASTERS (one master), SHITU_APPRENTICES. Run from research/shitu.
set -e
IFS=, read -ra APPS <<< "$SHITU_APPRENTICES"
M=$SHITU_MASTERS
python -X utf8 -c "
import trial_run as t
for n in ['$M'] + '$SHITU_APPRENTICES'.split(','):
    c = t.Client(n)
    if c.team():
        c.game.team_leave()
"
sleep 1
pids=()
for a in "${APPS[@]}"; do python -X utf8 take224.py "$a" & pids+=($!); done
python -X utf8 -c "
import take224, trial_run as t
from provisioner import world as w
c = t.Client('$M')
take224.to_boss(c)
take224.take(c)
take224.teleport(c)
" & pids+=($!)
for p in "${pids[@]}"; do wait $p; done
python -X utf8 go_cave.py
GATHERER=$M SHITU_GATHER_CAST=1 bash logs/gather_all.sh
echo R3_CAVE_DONE
