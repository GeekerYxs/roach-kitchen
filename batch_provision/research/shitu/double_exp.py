"""Claim the weekly 3-hour double exp at 散福老人 in 自由市场 (map 300), right after the 10 级 战士 转职.

    python -X utf8 research/shitu/double_exp.py 千万1 千万2 ...      (one window each; run them in parallel)

Recorded 2026-10-27 23:07 (自由一号 by hand, monitor), every step a plain NPC dialog (docs/SHITU_STATIONS.md 3.1):
  map 1 传送门 NPC 10213 (1338,1053)「自由市场」-> map 300
  散福老人 NPC 30 (1360,1275):「我要领取加倍时间」-> 1 / 2 / 3 小时 -> pick「3 小时」
      ->「你已经成功领取了 3 小时的加倍经验时间…」(+ S->C 0x42cf <I char><I 1001><I 10800>) ->「离开」
  map 300 传送门 NPC 24 (1781,1268)「逍遥村西区」-> map 1
Precondition: task 24 done (战士). Done once per apprentice: state.json step 'double3h'. If the week's allowance is
smaller than 3 hours, the largest offered amount is taken and logged.
"""
import re
import sys
import time

import trial_run as t
from bai_shi import done, mark
from provisioner import world as w
from take224 import talk
from zhuanzhi_finish import gate, walk

MARKET = 300
GATE_VILLAGE, GATE_VILLAGE_XY = 10213, (1338, 1053)
GATE_MARKET, GATE_MARKET_XY = 24, (1781, 1268)
SANFU, SANFU_XY = 30, (1360, 1275)
_HOURS = re.compile(r'(\d+)\s*小时')


def choose_hours(options):
    """(opt, hours) of the largest「我要领取 N 小时」on the menu, None when there is none."""
    best = None
    for opt, label in options:
        m = _HOURS.search(t.plain(label))
        if m and '领取' in t.plain(label) and (best is None or int(m.group(1)) > best[1]):
            best = (opt, int(m.group(1)))
    return best


def claim(c):
    if done(c.name, 'double3h'):
        t.say(f'[{c.name}] 已经领过双倍，跳过')
        return
    if not w.read_quest(c.mem, 24).done:
        raise t.Stop(f'{c.name} 还没转职（任务 24 没完成），先转职再领双倍')
    if c.world().map_id != MARKET:
        gate(c, GATE_VILLAGE, GATE_VILLAGE_XY, 1, '自由市场', MARKET)
    walk(c, MARKET, SANFU_XY, '散福老人')
    d = talk(c, SANFU, ['我要领取加倍时间'])
    pick = choose_hours(d.options) if d else None
    if not pick and d and '低于' in t.body(d):
        # 「只有你的加倍经验时间剩余时间低于10分钟，你才能重新领取」: 地瓜 double time is still running, come back later
        t.say(f'[{c.name}] 身上还有加倍时间（剩余 > 10 分钟），这次不领：{t.body(d)[-40:]}')
        c.game.select_dialog(d.options[0][0])
        time.sleep(0.5)
        gate(c, GATE_MARKET, GATE_MARKET_XY, MARKET, '逍遥村西区', 1)
        return
    if not pick:
        raise t.Stop(f'{c.name} 散福老人没有可领的时间: {t.body(d) if d else None} {d.options if d else None}')
    opt, hours = pick
    before = d.text
    c.game.select_dialog(opt)
    d = t.wait(lambda: (x := c.dialog()) and x.text != before and x, 5, f'{c.name} 领 {hours} 小时后的对话')
    text = t.body(d)
    if '成功领取' not in text:
        raise t.Stop(f'{c.name} 领双倍没成功: {text}')
    mark(c.name, 'double3h', hours=hours)
    t.say(f'[{c.name}] 领到 {hours} 小时双倍：{text[:30]}')
    if d.options:
        c.game.select_dialog(d.options[0][0])          # 离开
    time.sleep(0.5)
    gate(c, GATE_MARKET, GATE_MARKET_XY, MARKET, '逍遥村西区', 1)


if __name__ == '__main__':
    try:
        for n in sys.argv[1:]:
            c = t.Client(n)
            claim(c)
            if c.world().map_id == MARKET:                  # claimed before, still standing in the market
                gate(c, GATE_MARKET, GATE_MARKET_XY, MARKET, '逍遥村西区', 1)
    except t.Stop as e:
        t.say(f'停止: {e}')
        raise SystemExit(1)
