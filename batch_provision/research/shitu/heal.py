"""Out of battle, eat 萝卜糕 (64002, +30 HP each, live 17:2x) until HP is full or none is left.

    python -X utf8 research/shitu/heal.py 千万2 千万3 ...

HP comes from the 0x40e0 stats packet the server sends after every change (302 bytes, live 17:2x on 千万2):
<I char id><I hp><I 0><I mp><I 0><I max hp>... (965 -> 995 after one 萝卜糕, max 1987). We read the latest one on the
role's tap. Round 3: the apprentices ate all their 肉林 (auto refill), so HP stays low after battles.
"""
import struct
import sys
import time

import trial_run as t
from monitor import Tap
from provisioner import world as w

CAKE, GAIN = 64002, 30


def hp(c, tap, last):
    for _, d, op, body, _ in tap.poll():
        if op == 0x40e0 and len(body) == 302 and struct.unpack_from('<I', body, 0)[0] == c.char_id:
            last = struct.unpack_from('<6I', body, 0)
    return last


def heal(name):
    c = t.Client(name)
    rows = [b for _, d, op, b, _ in list(Tap(c.pid, from_end=False).poll())[-20000:]
            if op == 0x40e0 and len(b) == 302 and struct.unpack_from('<I', b, 0)[0] == c.char_id]
    if not rows:
        t.say(f'[{name}] 读不到血量')
        return
    last = struct.unpack_from('<6I', rows[-1], 0)
    tap = Tap(c.pid, from_end=True)
    tap.ready()
    start, ate = last[1], 0
    while last[1] + GAIN <= last[5]:
        t.wait(lambda: not c.world().in_battle, 120, f'{name} 战斗结束')
        s = next((s for s in w.read_bag(c.mem) if s.item_id == CAKE), None)
        if s is None:
            t.say(f'[{name}] 萝卜糕吃完了')
            break
        before = last[1]
        c.game.use_item(s.slot)
        end = time.monotonic() + 3
        while time.monotonic() < end and last[1] == before:
            last = hp(c, tap, last)
            time.sleep(0.1)
        if last[1] == before:
            t.say(f'[{name}] 吃了萝卜糕血没变，停')
            break
        ate += 1
    t.say(f'[{name}] 血 {start} -> {last[1]}/{last[5]}，吃了 {ate} 个萝卜糕，剩 {w.item_count(w.read_bag(c.mem), CAKE)}')


if __name__ == '__main__':
    for n in sys.argv[1:]:
        heal(n)
