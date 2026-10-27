"""Task 181 step 5: team per SHITU_MASTERS walks 逍遥村 1 -> 夕阳草原 130 -> 逍遥古迹 (650, entrance NPC 10162 at
(301,323)) -> 黑色水晶 NPC 986 (2542,3442) and stops there (maze_train goal stage, leader casts).

    python -X utf8 research/shitu/guji_crystal.py
"""
import maze_train as m

CRYSTAL = (2542, 3442)
m.STAGES = (
    dict(name='逍遥古迹 黑色水晶', goal=(650, CRYSTAL), maze=None, until=None, patrol_b=None,
         legs={1: ('walk', 130, (301, 323)),
               130: ('click', 10162, (301, 323)),
               650: ('walk', 650, CRYSTAL)}),
)

if __name__ == '__main__':
    try:
        m.main()
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
