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
        if m.t.Client(m.LEADER).world().map_id == 650:   # 2026-10-28 team B: a rerun from inside 古迹 walked 35 min
            stages = m.STAGES                            # toward the floor-1 entrance it could not reach; start over
            import r4_util                               # imports quanshou, which sets maze_train.STAGES
            m.STAGES = stages
            m.t.say('已经在逍遥古迹里，先全队回城再进')
            r4_util.home()
        m.main()
        lead = m.t.Client(m.LEADER)
        for attempt in range(3):         # 2026-10-28 伏地魔2: one click did nothing; step onto the spot and click again
            if lead.world().y > 5000:
                break
            if attempt:
                m.t.say(f'[{lead.name}] 第 {attempt} 次点 10153 没进二层，走到 (1428,924) 再点')
                lead.game.navigate(650, 1428, 924)
                m.t.wait(lambda: not lead.world().moving, 15, f'{lead.name} 走到二层入口')
            lead.game.click_npc(10153)
            try:
                m.t.wait(lambda: lead.world().y > 5000, 8, f'{lead.name} 进二层')
            except m.t.Stop:
                if attempt == 2:
                    raise
        m.t.say(f'[{lead.name}] 二层 ({lead.world().x:.0f},{lead.world().y:.0f})')
    except m.t.Stop as e:
        m.t.say(f'停止: {e}')
        raise SystemExit(1)
