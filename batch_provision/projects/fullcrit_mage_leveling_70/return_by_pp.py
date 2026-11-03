"""Return stragglers in the field to the village using only verified PP chicken menus."""
import _bootstrap  # noqa: F401
import time

import pp_chain
import trial_run as t
from common import APPRENTICES
from lunhui15 import LEADER


def main():
    for name in (LEADER,) + APPRENTICES:
        c = t.Client(name)
        for _ in range(8):
            st = c.world()
            if st.map_id in (1, 8):
                t.say(f'[{name}] 已在村里 map {st.map_id}')
                break
            if c.team():
                c.game.team_leave()
                t.wait(lambda: not c.team(), 5, f'{name} 离队')
            pp_chain.hop(c, [c], '逍遥村西区', ['龙之都', '平静海岸2区', '恶人山'])
        else:
            raise t.Stop(f'{name} 通过 PP鸡传送8次仍未回村，停下')
        if c.world().map_id not in (1, 8):
            raise t.Stop(f'{name} 未回村：map={c.world().map_id}')


if __name__ == '__main__':
    try:
        main()
    except t.Stop as exc:
        t.say(f'停止：{exc}')
        raise SystemExit(1)
