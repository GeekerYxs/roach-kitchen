"""伏地魔1 leads the four others from 龙之都外城 无尽2路口 to 遗忘洞穴 (map 750) and stops on arrival.

    python -X utf8 research/shitu/go_cave.py

Route (AutoPath/NPCDirection.csv): map 20 -> across the link 10192 (396,2976) -> 无尽平原2区 141 -> 遗忘洞穴 entrance
NPC 10166 (3410,252), clicked -> 750. Team, casting and talent as maze_train.py (it is maze_train's main loop with a
single goal stage).
"""
import maze_train as m

m.STAGES = (
    dict(name='遗忘洞穴', goal=(750, None), maze=None, until=None, patrol_b=None,
         legs={20: ('walk', 141, (3410, 252)),           # 龙之都外城 -> 无尽平原2区, straight to the cave entrance
               141: ('click', 10166, (3410, 252))}),     # 遗忘洞穴 entrance
)

if __name__ == '__main__':
    try:
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
