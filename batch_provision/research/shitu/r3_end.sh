# Round 3, one team in 蛇王卧室 after the snake: everybody 回城卷, sell junk (--safe), trial 3 (强劲之棍).
# No 解除师徒, no delete (user, round 3). Env: SHITU_STATE, SHITU_MASTERS, SHITU_APPRENTICES.
set -e
IFS=, read -ra APPS <<< "$SHITU_APPRENTICES"
python -X utf8 -c "
import trial_run as t
from quanshou import scroll
cs = [t.Client(n) for n in ['$SHITU_MASTERS'] + '$SHITU_APPRENTICES'.split(',')]
for c in cs:
    if c.team():
        c.game.team_leave()
for c in cs:
    t.wait(lambda: not c.team(), 5, f'{c.name} 离队')
    if c.world().map_id != 1:
        scroll(c)
"
python -X utf8 sell_tradable.py --safe "${APPS[@]}"
python -X utf8 trial3_run.py --master "$SHITU_MASTERS" "${APPS[@]}"
echo R3_END_DONE
