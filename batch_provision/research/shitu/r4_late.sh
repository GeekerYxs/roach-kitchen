{ # Round 4, one team at 40 级 (after r4_mid.sh): 任务 181 战士的试炼, 任务 183 勇者的考验 (转勇者), 出师, 礼包 + 邮  
# The command list of docs/SHITU_PIPELINE.md section 4, as run in round 3.
# Env: SHITU_STATE, SHITU_MASTERS (one master), SHITU_APPRENTICES (4). Run from research/shitu.
# FROM=<step> restarts at that step (names below). No gold is given away; 解除师徒 / delete are not done.
set -e
IFS=, read -ra APPS <<< "$SHITU_APPRENTICES"
M=$SHITU_MASTERS
FROM=${FROM:-q181}
U() { python -X utf8 r4_util.py "$@"; }
tc() { python -X utf8 talk_chain.py "$@" "${APPS[@]}"; }       # tc MAP X Y NPC WORD
step() { echo "== STEP $1 $(date +%H:%M:%S)"; }
go=0
prev=
at() {     # UNTIL=<step>: stop after that step (a catch-up run for some apprentices only)
  if [ $go = 1 ] && [ -n "$UNTIL" ] && [ "$prev" = "$UNTIL" ]; then echo R4_LATE_DONE; exit 0; fi
  prev=$1
  [ "$FROM" = "$1" ] && go=1; [ $go = 1 ] && echo "== STEP $1 $(date +%H:%M:%S)"; [ $go = 1 ]; }

export SHITU_QID=181
if at q181; then step q181
  U home; U double; U restock 20
  python -X utf8 sell_tradable.py --stones "${APPS[@]}"
  U space 4
  python -X utf8 pp_chain.py 龙之都 平静海岸2区
  python -X utf8 back_longeer.py
  tc 20 3174 1251 631 进行战士的试炼
fi
if at quan; then step quan
  if [ "$(python -X utf8 -c "import trial_run as t; print(t.Client('$M').world().map_id)" | tail -1)" = 1 ]; then
    python -X utf8 pp_chain.py 龙之都 平静海岸2区      # a supervisor restart scrolls home first
  fi
  python -X utf8 quan100.py
  python -X utf8 back_longeer.py
  tc 20 3174 1251 631 战士的试炼
  U need 181 3
fi
if at wulong; then step wulong
  python -X utf8 pp_chain.py 乌龙村 平静海岸2区
  tc 15 522 489 205 战士的试炼
  U need 181 4
  U home          # user 2026-10-28: everybody scrolls home; the tree trip starts in 逍遥村 with the team already together
fi
if at tree; then step tree
  U space 3
  python -X utf8 pp_chain.py 龙之都 平静海岸2区
  python -X utf8 go_goal.py 20 142 678 1977
  python -X utf8 team_npc.py 142 953 678 1977 拿起 181 "$M" "${APPS[@]}" --no-regroup
  U home; U double
  tc 8 894 459 304 战士的试炼
  U need 181 5
fi
if at crystal; then step crystal
  python -X utf8 guji_entrance.py
  python -X utf8 go_goal.py 650 650 2542 3442
  python -X utf8 team_npc.py 650 986 2542 3442 "战士|水晶|看" 181 "$M" "${APPS[@]}" --no-regroup
  U home; U double
  tc 8 894 459 304 战士的试炼
  U need 181 6
fi
if at dew; then step dew
  U space 3
  python -X utf8 tower1_go.py
  python -X utf8 dew_team.py "$M" $(printf '%s:0 ' "${APPS[@]}")
fi
if at pour; then step pour
  U home; U double
  python -X utf8 guji_entrance.py
  python -X utf8 go_goal.py 650 650 2542 3442
  python -X utf8 team_npc.py 650 986 2542 3442 "花露|拿起馒头" 181 "$M" "${APPS[@]}" --no-regroup
  U home; U double
  tc 8 894 459 304 战士的试炼
  python -X utf8 pp_chain.py 龙之都 平静海岸2区
  tc 20 3174 1251 631 战士的试炼
  U need 181 99
fi

export SHITU_QID=183
if at q183; then step q183
  if [ "$(python -X utf8 -c "import trial_run as t; print(t.Client('$M').world().map_id)" | tail -1)" = 1 ]; then
    python -X utf8 pp_chain.py 龙之都 平静海岸2区      # a supervisor restart scrolls home first
  fi
  python -X utf8 yongzhe_take.py "${APPS[@]}"
  python -X utf8 pp_chain.py 恶人山 平静海岸2区 龙之都
  python -X utf8 desert_go.py
  tc 170 1890 567 2202 勇者
  python -X utf8 scorpion_water.py "$M" "${APPS[@]}"
  U home; U double; U restock 20
  python -X utf8 pp_chain.py 龙之都 平静海岸2区
  tc 20 3174 1251 631 勇者
  tc 20 4806 309 577 勇者
  U need 183 4
fi
if at corpse; then step corpse
  U space 3
  python -X utf8 pp_chain.py 恶人山 平静海岸2区 龙之都
  python -X utf8 ruin_go.py 3030 4569
  python -X utf8 team_npc.py 1000 966 3030 4569 "勇者|安魂曲|拾取" 183 "$M" "${APPS[@]}" --no-regroup
  U home; U double
  python -X utf8 pp_chain.py 龙之都 平静海岸2区
  tc 20 4806 309 577 勇者
  U need 183 6
fi
if at king; then step king
  U space 3
  python -X utf8 pp_chain.py 恶人山 平静海岸2区 龙之都
  python -X utf8 ruin_go.py 2682 3285
  python -X utf8 scorpion_king.py "${APPS[0]}" "$M" "${APPS[@]:1}"
  U home; U double
  python -X utf8 sell_tradable.py --stones "${APPS[@]}"
  python -X utf8 pp_chain.py 龙之都 平静海岸2区
  tc 20 4806 309 577 勇者
  tc 20 3174 1251 631 勇者
  U need 183 8
fi
if at fairy; then step fairy
  U home; U double
  python -X utf8 -c "
import time, trial_run as t
from zhuanzhi_finish import gate, walk
from take224 import talk
from provisioner import world as w
for n in '$SHITU_APPRENTICES'.split(','):
    c = t.Client(n)
    if w.read_quest(c.mem, 183).active:
        gate(c, 10213, (1338, 1053), 1, '梦幻岛', 270)
        walk(c, 270, (1374, 628), '神仙姐姐')
        talk(c, 1, ['勇者的考验', '继续', '继续', '完成转职礼', '接受奖励'])
        t.wait(lambda: w.read_quest(c.mem, 183).done, 5, f'{n} 任务 183 完成')
        t.say(f'[{n}] 183 {w.read_quest(c.mem, 183)}')
        if c.dialog():
            c.game.select_dialog(0)
        time.sleep(0.5)
    if c.world().map_id == 270:
        gate(c, 23, (954, 507), 270, '逍遥村西区', 1)
"
fi
if at chushi; then step chushi
  U home; U double
  U space 2
  python -X utf8 chushi.py "$M" "${APPS[@]}"
fi
if at finish; then step finish
  python -X utf8 open_packs.py "${APPS[@]}" || true
  python -X utf8 sell_tradable.py --safe "${APPS[@]}" || true
  U space 6       # 2026-10-28 亿万15: 39/40 bag, mail_sell took nothing (33 mails left)
  python -X utf8 mail_sell.py "${APPS[@]}" || true
fi
echo R4_LATE_DONE
exit
}   # whole script in one group: bash parses it before running, so edits cannot shift a live run
