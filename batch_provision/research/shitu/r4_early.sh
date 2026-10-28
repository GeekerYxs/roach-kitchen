{ # Round 4, one team, freshly made apprentices in 逍遥村 -> 拜师 -> 古井 1->10 -> 10 级战士转职 + 任务 94 -
# 3 小时双倍 (散福老人) -> 补给 + 海岸 PP鸡 认证 -> 轮回之城 -> 暗影迷城 / 八阵图 -> 大个王.
# Env: SHITU_STATE, SHITU_MASTERS (one master), SHITU_APPRENTICES (4). Run from research/shitu.
# Every step skips what is already done, so a rerun continues.
set -e
IFS=, read -ra APPS <<< "$SHITU_APPRENTICES"
M=$SHITU_MASTERS
home() {   # everybody leaves the team and scrolls to 逍遥村
python -X utf8 -c "
import trial_run as t
from quanshou import scroll
cs = [t.Client(n) for n in ['$M'] + '$SHITU_APPRENTICES'.split(',')]
for c in cs:
    c.game.cancel_navigation()
    if c.team():
        c.game.team_leave()
import time; time.sleep(1)
for c in cs:
    t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    if c.world().map_id not in (1, 8):
        scroll(c)
"
}
par() {    # par SCRIPT [ARGS...]: run SCRIPT ARGS <apprentice> for every apprentice at once
pids=()
for a in "${APPS[@]}"; do python -X utf8 "$@" "$a" & pids+=($!); done
rc=0
for p in "${pids[@]}"; do wait $p || rc=1; done
return $rc
}
lv() {     # lowest apprentice level
python -X utf8 -c "
import trial_run as t
from provisioner import world as w
print(min(w.read_level(t.Client(n).mem) for n in '$SHITU_APPRENTICES'.split(',')))" | tail -1
}
python -X utf8 bai_shi.py --master "$M" "${APPS[@]}"
if [ "$(lv)" -lt 10 ]; then python -X utf8 well10.py; fi
home
python -X utf8 r4_util.py supply
par zhuanzhi_take.py
need=$(python -X utf8 -c "
import trial_run as t
from provisioner import world as w
from bai_shi import done
print(sum(tuple(w.read_quest(t.Client(n).mem, 24).steps) == (0, 0, 1) and not done(n, 'kills5') for n in '$SHITU_APPRENTICES'.split(',')))" | tail -1)
if [ "$need" -gt 0 ]; then python -X utf8 quanshou.py; fi
par zhuanzhi_take.py --handin
par zhuanzhi_finish.py
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
par double_exp.py      # user 2026-10-28: 3 小时 at 散福老人 right after the 转职 (no 地瓜 eaten before)
python -X utf8 supply_go.py
python -X utf8 pp_unlock.py "${APPS[@]}"
if [ "$(lv)" -lt 15 ]; then python -X utf8 lunhui15.py; fi
python -X utf8 maze_train.py
echo R4_EARLY_DONE
exit
}   # whole script in one group: bash parses it before running, so edits cannot shift a live run
