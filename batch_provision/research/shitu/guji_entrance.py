"""Team per SHITU_MASTERS: 逍遥村 1 -> 夕阳草原 130 -> 逍遥古迹 650 (entrance NPC 10162 at (301,323)) -> the 二层
entrance at (1428,924) (user 16:0x: 「逍遥古迹也有二层，你得通过 1400,900 那里进入」; stepping on it moves the team to
(1650,5463) on the same map id). Stepping on it is not enough every time: 17:04 伏地魔2 went through, 伏地魔1 stood
at (1428,924) and (1400,900) on floor 1; ClickNpc(10153) there moved it at once (17:09). So after arriving the leader
clicks 10153 unless it is already on floor 2 (y > 5000). Then go_goal.py 650 650 2542 3442 walks to the 黑色水晶 (986).

    python -X utf8 research/shitu/guji_entrance.py
"""
import maze_train as m

m.STAGES = (
    dict(name='逍遥古迹 二层入口', goal=(650, (1428, 924)), maze=None, until=None, patrol_b=None,
         legs={1: ('walk', 130, (301, 323)),
               130: ('click', 10162, (301, 323))}),
)

if __name__ == '__main__':
    try:
        m.main()
        lead = m.t.Client(m.LEADER)
        if lead.world().y < 5000:
            lead.game.click_npc(10153)
            m.t.wait(lambda: lead.world().y > 5000, 5, f'{lead.name} 进二层')
        m.t.say(f'[{lead.name}] 二层 ({lead.world().x:.0f},{lead.world().y:.0f})')
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
