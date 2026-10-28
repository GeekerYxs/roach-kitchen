{ # Round 4, one team from 大个王 (after r4_early.sh, 23 级) to 40 级 — user's route 2026-10-28
# 考验一二 -> 八阵图 to 25 -> 遗忘洞穴 25->28 (the master holds task 224 and gathers 9 花 + 3 石 on the way) ->
# 224 for the apprentices -> 地头蛇 (boss 题自动答) -> 通天塔一区 28->33 -> 考验三 -> 礼包 / 装备 / 保护道具 ->
# 通天塔二区 33->40 (breaks off for the 散福 3 小时 when the 地瓜 double runs out).
# Env: SHITU_STATE, SHITU_MASTERS (one master), SHITU_APPRENTICES (4). Run from research/shitu.
# FROM=start|bazhen|cave|q224|snake|tower1|end|packs|tower2 restarts at that step; level checks skip finished leveling.
set -e
IFS=, read -ra APPS <<< "$SHITU_APPRENTICES"
M=$SHITU_MASTERS
FROM=${FROM:-start}
go=0
at() { [ "$FROM" = "$1" ] && go=1; [ $go = 1 ] && echo "== STEP $1 $(date +%H:%M:%S)"; [ $go = 1 ]; }
home() { python -X utf8 r4_util.py home; }
lv() {
python -X utf8 -c "
import trial_run as t
from provisioner import world as w
print(min(w.read_level(t.Client(n).mem) for n in '$SHITU_APPRENTICES'.split(',')))" | tail -1
}
if at start; then
  home
  python -X utf8 sell_tradable.py --safe "${APPS[@]}"
  python -X utf8 trial_run.py --armor 3 --master "$M" "${APPS[@]}"
fi
if at bazhen; then
  if [ "$(lv)" -lt 25 ]; then
    home
    python -X utf8 pp_chain.py 平静海岸2区
    python -X utf8 bazhen25.py 25
  fi
fi
if at cave; then
  home
  python -X utf8 pp_chain.py 龙之都 平静海岸2区
  python -X utf8 r4_util.py leave
  python -X utf8 -c "
import take224, trial_run as t
c = t.Client('$M')
take224.to_boss(c)
take224.take(c)
"
  python -X utf8 go_cave.py
  GATHERER=$M SHITU_GATHER_CAST=1 bash logs/gather_all.sh
  if [ "$(lv)" -lt 28 ]; then python -X utf8 cave_train.py 28; fi
fi
if at q224; then
  home
  python -X utf8 pp_chain.py 龙之都 平静海岸2区
  python -X utf8 r4_util.py leave
  pids=()
  for a in "${APPS[@]}"; do python -X utf8 take224.py "$a" & pids+=($!); done
  for p in "${pids[@]}"; do wait $p; done
fi
if at snake; then
  python -X utf8 go_cave.py
  python -X utf8 dts.py
fi
# user 2026-10-28 00:5x: no 28->30 in the cave; 通天塔一区 28->33 (more exp), 考验三 (needs 30) afterwards
if at tower1; then
  if [ "$(lv)" -lt 33 ]; then
    home
    python -X utf8 r4_util.py double
    python -X utf8 pp_chain.py 通天塔 平静海岸2区
    python -X utf8 tower28.py 33
  fi
fi
if at end; then
  bash r3_end.sh
fi
if at packs; then
  python -X utf8 r4_util.py double
  python -X utf8 drop_prank.py "${APPS[@]}" || true
  python -X utf8 drop_prank.py --name 新手洗点卡 "${APPS[@]}" || true
  python -X utf8 open_packs.py "${APPS[@]}" || true
  python -X utf8 wear_best.py "${APPS[@]}" || true
  python -X utf8 eat_items.py --name 幸运丸 --name 心脏起搏器 --name 小酒池 --name 小肉林 "${APPS[@]}" || true
fi
if at tower2; then
  if [ "$(lv)" -lt 40 ]; then
    home
    python -X utf8 r4_util.py double
    python -X utf8 tower2_go.py
    python -X utf8 tower2_patrol.py 40     # breaks off for the 散福 3 小时 when the 地瓜 double runs out
  fi
fi
echo R4_MID_DONE
exit
}   # whole script in one group: bash parses it before running, so edits cannot shift a live run
