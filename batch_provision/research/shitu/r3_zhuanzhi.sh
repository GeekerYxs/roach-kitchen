# Round 3, one team, from 大个王 (after maze_train) to 转职 done + task 94, back in 逍遥村 map 1.
# Env: SHITU_STATE, SHITU_MASTERS (one master), SHITU_APPRENTICES (4). Run from research/shitu.
#   1. 飞鞋 record next to 大个王 (shoe_dagewang)
#   2. the master's task 224 (2,1) -> hand in at 大个王 + take again = (1,)  (take224.take, no teleport)
#   3. everybody 回城卷 to map 1
#   4. 转职: take task 24 (apprentices in parallel, own windows), 拳手 (team), hand in, 梦幻岛, NPC 308 task 94
#   5. 3 小时双倍 at 散福老人 in 自由市场 (double_exp.py, apprentices in parallel), back in map 1
set -e
IFS=, read -ra APPS <<< "$SHITU_APPRENTICES"
M=$SHITU_MASTERS
python -X utf8 shoe_dagewang.py
python -X utf8 -c "
import take224, trial_run as t
from provisioner import world as w
c = t.Client('$M')
take224.take(c)
t.say(f'[{c.name}] 224 {w.read_quest(c.mem, 224)}')
"
python -X utf8 -c "
import trial_run as t
from quanshou import scroll
for n in ['$M'] + '$SHITU_APPRENTICES'.split(','):
    c = t.Client(n)
    if c.world().map_id != 1:
        scroll(c)
"
pids=()
for a in "${APPS[@]}"; do python -X utf8 zhuanzhi_take.py "$a" & pids+=($!); done
for p in "${pids[@]}"; do wait $p; done
python -X utf8 quanshou.py
pids=()
for a in "${APPS[@]}"; do python -X utf8 zhuanzhi_take.py --handin "$a" & pids+=($!); done
for p in "${pids[@]}"; do wait $p; done
pids=()
for a in "${APPS[@]}"; do python -X utf8 zhuanzhi_finish.py "$a" & pids+=($!); done
for p in "${pids[@]}"; do wait $p; done
python -X utf8 -c "
import trial_run as t
from zhuanzhi_finish import walk
from take224 import talk
from provisioner import world as w
for n in '$SHITU_APPRENTICES'.split(','):
    c = t.Client(n)
    if w.read_quest(c.mem, 94).active:
        walk(c, 1, (1278, 1135), 'NPC 308')
        d = talk(c, 308, ['村庄的希望'])
        t.say(f'[{n}] 任务 94 {w.read_quest(c.mem, 94)} 对话 {t.body(d)[:40] if d else None}')
        if d:
            c.game.select_dialog(0)
"
pids=()
for a in "${APPS[@]}"; do python -X utf8 double_exp.py "$a" & pids+=($!); done
for p in "${pids[@]}"; do wait $p; done
echo R3_ZHUANZHI_DONE
