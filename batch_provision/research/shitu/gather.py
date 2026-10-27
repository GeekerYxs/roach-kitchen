"""Gather 遗忘之花 in 遗忘洞穴 (map 750) with the team leader until the bag holds TARGET of them.

    python -X utf8 research/shitu/gather.py [role] [target]              (default: 欧皇 20) 遗忘之花 until target
    python -X utf8 research/shitu/gather.py [role] [count] dark          暗·遗忘之花: `count` gathers, the flowers
                                                                         nearest 蛇王卧室入口 first
    python -X utf8 research/shitu/gather.py [role] [stones] stones       暗·遗忘之花 until the bag holds `stones`
                                                                         遗忘之石

Protocol (recorded 2026-10-26 22:44, see GATHER.md): a flower is an NPC. ClickNpc(npc) -> 0x0050 <I0><I npc>,
server answers 0x4019 with one option「采集遗忘之花」; SelectDialog(1) -> 0x0051 <I0><I1><I0>, server answers
0x46ff (count message) + 0x4020 (bag slot update), no cast bar. A picked flower answers「刚刚采过…过些时日」
with only「离开」 until it regrows.
Route: nearest flower not known to be regrowing, official path-finder Navigate(750, x, y); a battle on the way is
left to the user's auto-skill, we only wait for in_battle to clear and walk on.
No UI clicks: ClickNpc / SelectNpcDialogEntry / Navigate game functions (DLL command 106); reading = ReadProcessMemory.
"""
import math
import os
import sys
import time
from datetime import datetime

from common import LOGS, RUNTIME, find_roles, module_base
from monitor import Tap, texts
from provisioner import native, world as w
from provisioner.game import Game
from provisioner.memory import ProcessMemory

MAP = 750
FLOWER_ITEM, STONE_ITEM = 11150, 11151
# NPCDirection.csv rows 1483-1500: 遗忘之花 npc id, x, y (map 750). 暗·遗忘之花 4167-4182 are not used here.
FLOWERS = {
    4183: (1946, 2430), 4184: (450, 3330), 4185: (2085, 930), 4186: (390, 2250), 4187: (2887, 3330),
    4188: (3360, 1830), 4189: (1886, 453), 4190: (2666, 2385), 4191: (577, 1537), 4192: (4346, 3285),
    4193: (1368, 1811), 4194: (3378, 915), 4195: (2688, 1485), 4196: (1125, 502), 4197: (1147, 2685),
    4198: (1061, 945), 4199: (2658, 585), 4200: (4057, 2227),
}
# NPCDirection.csv rows 1467-1482: 暗·遗忘之花 (lower part of map 750, around 蛇王卧室入口 npc 10214 (3306,6183))
DARK = {
    4167: (4215, 7432), 4168: (1706, 6772), 4169: (1893, 5568), 4170: (1327, 7841), 4171: (3686, 6682),
    4172: (483, 4395), 4173: (2298, 6817), 4174: (435, 6153), 4175: (2662, 4121), 4176: (1046, 4770),
    4177: (4136, 5662), 4178: (450, 7597), 4179: (4226, 4522), 4180: (1125, 6588), 4181: (2835, 6146),
    4182: (1657, 4620),
}
SNAKE_DOOR = (3306, 6183)
# maplink.csv: 750 -> 750 links between the two floors (same map id, not connected on foot; walking into the rect
# teleports). Upper floor = the 遗忘之花 (y <= ~3500), lower floor = 暗·遗忘之花 (y >= ~4100).
TO_LOWER = (2304, 1320)        # rect (2256,1272)-(2352,1368), user: "大概在2300，1300"
TO_UPPER = (2628, 7656)        # rect (2568,7608)-(2688,7704)
FLOOR_SPLIT_Y = 3800
DARK_POOL = 6              # dark mode only visits the 6 dark flowers nearest the door
NEAR = 80                  # stand this close before clicking (the demo click was from 8 px)
STUCK_AFTER = 4.0          # no movement this long while not there -> navigate again
WALK_TIMEOUT = 180
GATHER_MARK = '采集'      # option「采集遗忘之花」; dark flowers: any option with 采集 (label not seen yet)
REGROW_MARK = '刚刚采过'

LOGS.mkdir(exist_ok=True)
_log = open(LOGS / f'gather_{datetime.now():%Y%m%d_%H%M%S}.log', 'w', encoding='utf-8')


def say(msg):
    line = f'{datetime.now():%H:%M:%S.%f}'[:-3] + ' ' + msg
    print(line, flush=True)
    _log.write(line + '\n')
    _log.flush()


class Stop(Exception):
    pass


class Leader:
    def __init__(self, name):
        found = find_roles((name,))
        if name not in found:
            raise Stop(f'{name} 的窗口没找到')
        self.name, self.pid = name, found[name][0]
        if not native.has_dll(self.pid) or native.read_status(self.pid)['stage'] != native.WORLD_STAGE:
            raise Stop(f'{name} 里没有加载好的 DLL，先跑 attach_tap.py {name}')
        st = native.read_status(self.pid)
        self.mem = ProcessMemory(self.pid, module_base(self.pid))
        self.game = Game(native.Session(self.pid, st['hwnd'], st['game_base']), self.mem)
        self.tap = Tap(self.pid, from_end=True)
        self.caster = None
        if os.environ.get('SHITU_GATHER_CAST') == '1':
            from lunhui15 import Caster
            self.caster = Caster(self)

    def world(self):
        return w.read_world(self.mem)

    def counts(self):
        bag = w.read_bag(self.mem) or ()
        return w.item_count(bag, FLOWER_ITEM), w.item_count(bag, STONE_ITEM)

    def server_messages(self):
        """0x46ff system messages since the last call (plain text, colour codes left in)."""
        try:
            return [' '.join(texts(body)) for _, d, op, body, _ in self.tap.poll() if d == 'S->C' and op == 0x46ff]
        except Exception as e:
            return [f'<录包读取出错 {e}>']


def wait(cond, timeout, what):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(0.1)
    raise Stop(f'{timeout}s 内没等到: {what}')


def wait_battle(me):
    if not me.world().in_battle:
        return
    say(f'[{me.name}] 战斗中，等战斗结束（' + ('自己放扫射 + 宠物烈焰爆发' if me.caster else '自动技能在打') + '）')
    t0 = time.monotonic()
    while me.world().in_battle:
        if me.caster:                                    # env SHITU_GATHER_CAST=1 (round 3: 欧皇 gathers alone)
            me.caster.tick(time.monotonic())
        time.sleep(0.15 if me.caster else 0.3)
    if me.caster:
        me.caster.reset()
        if time.monotonic() - t0 > 600:
            raise Stop('战斗超过 10 分钟没结束')
    say(f'[{me.name}] 战斗结束，用时 {time.monotonic() - t0:.0f}s')
    time.sleep(1.0)                                     # let the map scene come back before walking


def walk_to(me, npc, xy):
    t0 = time.monotonic()
    issued, last_pos, last_move = 0.0, None, time.monotonic()
    while True:
        wait_battle(me)
        st = me.world()
        if st.map_id != MAP:
            raise Stop(f'不在遗忘洞穴了 (map {st.map_id})')
        d = math.dist((st.x, st.y), xy)
        if d <= NEAR and not st.moving:
            return d
        pos = (int(st.x), int(st.y))
        if pos != last_pos:
            last_pos, last_move = pos, time.monotonic()
        if not issued or (time.monotonic() - last_move > STUCK_AFTER and time.monotonic() - issued > STUCK_AFTER):
            say(f'[{me.name}] 寻路去花 {npc} {xy}（现在 {pos}，距离 {d:.0f}）')
            me.game.navigate(MAP, *xy)
            issued = last_move = time.monotonic()
        if time.monotonic() - t0 > WALK_TIMEOUT:
            raise Stop(f'{WALK_TIMEOUT}s 没走到花 {npc}')
        time.sleep(0.2)


def change_floor(me, lower):
    """Walk into the floor link when the wanted flowers are on the other floor."""
    if (me.world().y > FLOOR_SPLIT_Y) == lower:
        return
    link = TO_LOWER if lower else TO_UPPER
    say(f'[{me.name}] 换层：去{"下" if lower else "上"}层，走进出入口 {link}')
    t0, issued = time.monotonic(), 0.0
    while (me.world().y > FLOOR_SPLIT_Y) != lower:
        wait_battle(me)
        st = me.world()
        if not issued or (not st.moving and time.monotonic() - issued > STUCK_AFTER):
            me.game.navigate(MAP, *link)
            issued = time.monotonic()
        if time.monotonic() - t0 > WALK_TIMEOUT:
            raise Stop(f'{WALK_TIMEOUT}s 没换到{"下" if lower else "上"}层，现在 {int(st.x)},{int(st.y)}')
        time.sleep(0.2)
    st = me.world()
    say(f'[{me.name}] 已换层，现在 ({int(st.x)},{int(st.y)})')
    time.sleep(1.0)


def gather_one(me, npc):
    """'ok' (bag grew) | 'ambush' (picked, a battle started) | 'regrow' | 'battle' (fight before picking) | 'nothing…'."""
    if me.world().dialog:                                # a dialog left open would be read as the answer
        me.game.select_dialog(0)
        wait(lambda: not me.world().dialog, 3, '关掉旧对话')
    before = me.counts()
    me.server_messages()                                 # drop older messages
    me.game.click_npc(npc)
    d = wait(lambda: (s := me.world()) and (s.dialog or s.in_battle) and s, 5, f'点花 {npc} 后的对话')
    if d.in_battle:
        return 'battle'
    pick = [(o, l) for o, l in d.dialog.options if GATHER_MARK in l]
    say(f'[{me.name}]   对话: {d.dialog.text.strip()[:120]!r} 选项 {d.dialog.options}')
    if REGROW_MARK in d.dialog.text or not pick:
        me.game.select_dialog(0)                         # 离开
        return 'regrow' if REGROW_MARK in d.dialog.text else f'nothing: {d.dialog.text!r}'
    me.game.select_dialog(pick[0][0])
    try:
        wait(lambda: me.counts() != before or me.world().in_battle, 5, '背包里遗忘之花变多')
    except Stop:
        pass
    time.sleep(0.3)
    for m in me.server_messages():
        say(f'[{me.name}]   服务器消息: {m}')
    after = me.counts()
    if after != before:
        say(f'[{me.name}]   采到！遗忘之花 {before[0]} -> {after[0]}，遗忘之石 {before[1]} -> {after[1]}')
        return 'ok'
    return 'ambush' if me.world().in_battle else 'nothing: 背包没变'


def main(name, target, dark=False, stones_mode=False):
    dark = dark or stones_mode
    me = Leader(name)
    team = w.read_team(me.mem)
    if team and team.members and team.members[0] != me.world().char_id:
        raise Stop(f'{name} 不是队长 {team.members}')
    table = FLOWERS
    if dark:
        table = dict(sorted(DARK.items(), key=lambda kv: math.dist(kv[1], SNAKE_DOOR))[:DARK_POOL])
        say(f'[{name}] 暗·遗忘之花，离蛇王卧室入口最近的 {DARK_POOL} 朵: {table}')
    regrowing = {}                                       # npc -> time we saw it regrowing / picked it
    rounds, picked, start = 0, 0, me.counts()
    while True:
        flowers, stones = me.counts()
        say(f'[{name}] 背包：遗忘之花 {flowers}，遗忘之石 {stones}' + (f'；暗花已采 {picked}/{target}' if dark else ''))
        if (stones if stones_mode else picked if dark else flowers) >= target:
            say(f'[{name}] 完成：{"暗花采了 " + str(picked) + " 次" if dark else "遗忘之花 " + str(flowers)}，'
                f'这次共得 遗忘之花 {flowers - start[0]:+d}，遗忘之石 {stones - start[1]:+d}')
            return
        wait_battle(me)
        st = me.world()
        fresh = [n for n in table if n not in regrowing]
        if not fresh:
            rounds += 1
            oldest = min(regrowing, key=regrowing.get)
            age = time.time() - regrowing[oldest]
            say(f'[{name}] {len(table)} 朵都采过/在长，第 {rounds} 轮：回最早那朵 {oldest}（{age:.0f}s 前）再试')
            if age < 185:                                # server said: regrows after 3 minutes
                say(f'[{name}]   离 3 分钟还差 {185 - age:.0f}s，原地等')
                time.sleep(185 - age)
            if rounds > 20:
                raise Stop('转了 20 轮还没采够')
            fresh = [oldest]
            regrowing.pop(oldest)
        change_floor(me, dark)
        st = me.world()
        npc = min(fresh, key=lambda n: math.dist((st.x, st.y), table[n]))
        dist = walk_to(me, npc, table[npc])
        result = gather_one(me, npc)
        say(f'[{name}] 花 {npc} {table[npc]}（站在 {dist:.0f} px 外）: {result}')
        if result == 'battle':
            wait_battle(me)                              # fight before picking: try the same flower again afterwards
            continue
        if result in ('ok', 'ambush'):
            picked += 1
            if result == 'ambush':
                wait_battle(me)
                time.sleep(0.5)
                say(f'[{name}]   伏击战后背包: 遗忘之花/遗忘之石 = {me.counts()}')
        regrowing[npc] = time.time()


if __name__ == '__main__':
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else '欧皇', int(sys.argv[2]) if len(sys.argv) > 2 else 20,
             'dark' in sys.argv[3:], 'stones' in sys.argv[3:])
    except Stop as e:
        say(f'停止: {e}')
        raise SystemExit(1)
