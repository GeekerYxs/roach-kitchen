"""Team per SHITU_MASTERS walks from 无尽平原3区 (142) back to 龙格尔男爵 (NPC 631, 龙之都外城 20 (3174,1251)) to hand in task 181.

    python -X utf8 research/shitu/back_longeer.py

maze_train's loop with a single goal stage (as go_cave.py): the leader casts in any battle on the way and stops at the NPC.
"""
import maze_train as m

m.STAGES = (
    dict(name='龙格尔男爵', goal=(20, (3174, 1251)), maze=None, until=None, patrol_b=None,
         legs={142: ('walk', 20, (3174, 1251))}),       # 无尽平原3区 -> 龙之都外城 龙格尔男爵
)

if __name__ == '__main__':
    try:
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
