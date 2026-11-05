"""The 师徒 route of one batch as data: make -> early -> mid -> late, one Step per restart point.

This is the single source of truth the runner executes (it replaces r4_batch.sh + r4_early/mid/late.sh, which stay
in the repo as the round-4 fallback). Step names are the old FROM names, so docs and logs keep meaning the same.

A Step is a list of Cmds run in order; any Cmd that exits non-zero (and is not soft) fails the step, the runner then
cleans up (step.retry: 'home' = everybody scrolls to 逍遥村, 'leave' = leave the team where they stand) and reruns
the whole step. Every stage script skips what is already done, so a rerun continues.

Cmd tokens:
  first token  'U' = r4_util.py, 'ops' = python -m line.ops, else a script in research/shitu
  {M} master   {APPS} all apprentices (splat)   {A0} first one   {REST} the others (splat)
  {A} one apprentice: the Cmd runs once per apprentice, all at once (par=True)
  {APPS:0} 'name:0' per apprentice (dew_team)   {PAIRS} 'capNN:name' (splat)   {PREV} previous batch's names
  {T1} the team's tower1 target level (also inside Step.unless)
  {T2} the team's tower2 target: '40' or 'L+E' (ROUTE_BPLUS; Step.unless 'exp_ge {T2}')
  {LV:key} the team's level for leaving a map (plan.LEVELS: lunhui maze1 maze2 bazhen cave; also in when / unless)
Cmd.when = ops condition ('lv_lt 25', 'master_on 1', 'kills5'): the Cmd only runs when it holds.
Step.unless = ops condition: the whole step is skipped when it holds (leveling already done).

Lessons from rounds 1-4 that are rules here (tests/test_line.py checks them):
  - a step that ends by going home never regroups first (team_npc --no-regroup; user 2026-10-28)
  - every late quest step ends with a gate `U need QID N` (a lagging apprentice is caught at the step it fell behind)
  - nothing runs from logs/ (gitignored: round 4's cave step ran logs/gather_all.sh, absent from a fresh clone)
  - before steps that pick up quest items the bag gets free slots (U space; a full bag loses them silently)
"""
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Cmd:
    args: tuple
    when: str = None
    soft: bool = False               # failure is logged, the step goes on (old `|| true`)

    @property
    def par(self):
        return '{A}' in self.args


@dataclass(frozen=True)
class Step:
    name: str
    stage: str                       # make | early | mid | late
    cmds: tuple
    retry: str = 'home'              # cleanup before a rerun: home | leave | none
    unless: str = None
    env: dict = field(default_factory=dict)


def C(*args, when=None, soft=False):
    return Cmd(tuple(args), when, soft)


def tc(*args):                       # talk_chain MAP X Y NPC WORD for every apprentice
    return C('talk_chain.py', *map(str, args), '{APPS}')


PP_HOME = C('pp_chain.py', '龙之都', '平静海岸2区', when='master_on 1')    # a restart scrolled home first
# lunhui15 / maze_train only know the way from 平静海岸2区 (81) on: a team the recovery scrolled home (2026-11-05 live,
# 欧皇 team: 「在意外的地图 1」 on every retry, relog + home, again -> 停摆) first rides the PP鸡 to 81
PP_COAST = C('pp_chain.py', '平静海岸2区', when='master_on 1')
HOME, DOUBLE = C('U', 'home'), C('U', 'double')

ROUTE = (
    # ---- make: the batch's roles (slot BATCH of the team's accounts), tap armed, master's 回城卷
    Step('close_prev', 'make', (C('ops', 'close', '{PREV}'),), retry='none'),
    Step('make', 'make', (C('make_apprentices.py', '{PAIRS}'),), retry='none'),
    Step('arm', 'make', (C('ops', 'arm', '{APPS}'), C('U', 'restock_master', '100')), retry='none'),

    # ---- early: 拜师 -> 古井 1->10 -> 10 级转职 + 任务 94 -> 3 小时双倍 -> 补给 + PP鸡 -> 轮回之城 -> 迷城/八阵图 -> 大个王
    Step('bai_shi', 'early', (C('bai_shi.py', '--master', '{M}', '{APPS}'),), retry='leave'),
    Step('well', 'early', (C('well10.py'),), retry='leave', unless='lv_ge 10'),
    Step('zhuanzhi', 'early', (
        C('ops', 'home_village'),
        C('U', 'supply'),
        C('zhuanzhi_take.py', '{A}'),
        C('quanshou.py', when='kills5'),
        C('zhuanzhi_take.py', '--handin', '{A}'),
        C('zhuanzhi_finish.py', '{A}'),
        C('ops', 'q94'),
    ), retry='leave'),
    Step('double3h', 'early', (C('double_exp.py', '{A}'),), retry='leave'),     # user: 3 小时 right after 转职
    # the master talks too: 飞天 / 舔尊 (2026-10-28 batch 3) never ran this line, their PP鸡 permission is unknown
    Step('pp', 'early', (C('supply_go.py'), C('pp_unlock.py', '{M}', '{APPS}')), retry='leave'),
    Step('lunhui', 'early', (PP_COAST, C('lunhui15.py', '{LV:lunhui}')), retry='leave', unless='lv_ge {LV:lunhui}'),
    Step('maze', 'early', (PP_COAST, C('maze_train.py', '{LV:maze1}', '{LV:maze2}', '--stay')), retry='leave'),

    # ---- mid: 考验一二 -> 八阵图 25 -> 遗忘洞穴 25->28 (+采集) -> 224 -> 地头蛇 -> 通天一 28->33 -> 考验三 -> 二区 ->40
    Step('start', 'mid', (HOME, C('sell_tradable.py', '--safe', '{APPS}'),
                          C('trial_run.py', '--armor', '3', '--master', '{M}', '{APPS}')), retry='leave'),
    Step('bazhen', 'mid', (HOME, C('pp_chain.py', '平静海岸2区'), C('bazhen25.py', '{LV:bazhen}')),
         retry='leave', unless='lv_ge {LV:bazhen}'),
    Step('cave', 'mid', (
        HOME, C('pp_chain.py', '龙之都', '平静海岸2区'), C('U', 'leave'),
        C('ops', 'take224_master'),
        C('go_cave.py'),
        C('ops', 'gather'),                                  # the master: 9 花 + 3 遗忘之石 (was logs/gather_all.sh)
        C('cave_train.py', '{LV:cave}', when='lv_lt {LV:cave}'),
    ), retry='leave'),
    Step('q224', 'mid', (HOME, C('pp_chain.py', '龙之都', '平静海岸2区'), C('U', 'leave'),
                         C('take224.py', '{A}')), retry='leave'),
    # starts at 无尽2路口 (q224) or in the cave (a rerun after leave); anywhere else (2026-10-28 伏地魔1 dropped,
    # relogged, everybody home) the q224 trip comes first, else go_cave stops on the unexpected map every time
    Step('snake', 'mid', (
        C('U', 'home', when='master_off 20 750'),
        C('pp_chain.py', '龙之都', '平静海岸2区', when='master_on 1'),
        C('U', 'leave', when='master_on 20'),
        C('take224.py', '{A}', when='master_on 20'),
        C('go_cave.py'), C('dts.py'),
    ), retry='leave'),
    # {T1}: the team's tower1 target (line.toml tower1, default 35 since 2026-10-30; round 6 tried 35 for 伏地魔, whose 二区
    # battles need two rounds (ROUND5_NOTES.md)
    Step('tower1', 'mid', (HOME, DOUBLE, C('pp_chain.py', '通天塔', '平静海岸2区'), C('tower28.py', '{T1}')),
         retry='leave', unless='lv_ge {T1}'),
    Step('end', 'mid', (HOME, C('sell_tradable.py', '--safe', '{APPS}'),
                        C('trial3_run.py', '--master', '{M}', '{APPS}')), retry='leave'),
    Step('packs', 'mid', (
        DOUBLE,
        C('drop_prank.py', '{APPS}', soft=True),
        C('drop_prank.py', '--name', '新手洗点卡', '{APPS}', soft=True),
        C('open_packs.py', '{APPS}', soft=True),
        C('wear_best.py', '{APPS}', soft=True),
        C('eat_items.py', '--name', '幸运丸', '--name', '心脏起搏器', '--name', '小酒池', '--name', '小肉林', '{APPS}', soft=True),
    ), retry='leave'),
    Step('tower2', 'mid', (HOME, DOUBLE, C('tower2_go.py'), C('tower2_patrol.py', '40')),
         retry='leave', unless='lv_ge 40'),

    # ---- late: 任务 181 战士的试炼 -> 任务 183 勇者的考验 (转勇者) -> 出师 -> 礼包 + 邮件
    Step('q181', 'late', (
        HOME, DOUBLE, C('U', 'restock', '20'),
        C('sell_tradable.py', '--stones', '{APPS}'),
        C('U', 'space', '4'),
        C('pp_chain.py', '龙之都', '平静海岸2区'),
        C('back_longeer.py'),
        tc(20, 3174, 1251, 631, '进行战士的试炼'),
        C('U', 'need', '181', '1'),             # taken by all (an active quest has >= 1 step; r4_late had no gate)
    ), env={'SHITU_QID': '181'}),
    Step('quan', 'late', (
        PP_HOME, C('quan100.py'), C('back_longeer.py'),
        tc(20, 3174, 1251, 631, '战士的试炼'),
        C('U', 'need', '181', '3'),
    ), env={'SHITU_QID': '181'}),
    Step('wulong', 'late', (
        C('pp_chain.py', '乌龙村', '平静海岸2区'),
        tc(15, 522, 489, 205, '战士的试炼'),
        C('U', 'need', '181', '4'),
        HOME,                                   # user 2026-10-28: everybody scrolls home, the tree trip starts there
    ), env={'SHITU_QID': '181'}),
    Step('tree', 'late', (
        C('U', 'space', '3'),
        C('pp_chain.py', '龙之都', '平静海岸2区'),
        C('go_goal.py', '20', '142', '678', '1977'),
        C('team_npc.py', '142', '953', '678', '1977', '拿起', '181', '{M}', '{APPS}', '--no-regroup'),
        HOME, DOUBLE,
        tc(8, 894, 459, 304, '战士的试炼'),
        C('U', 'need', '181', '5'),
    ), env={'SHITU_QID': '181'}),
    Step('crystal', 'late', (
        C('U', 'space', '4'),                   # 2026-10-29: the apprentices NPC 986 ignored had 0-2 free slots
        C('guji_entrance.py'),
        C('go_goal.py', '650', '650', '2542', '3442'),
        C('team_npc.py', '650', '986', '2542', '3442', '战士|水晶|看', '181', '{M}', '{APPS}', '--no-regroup'),
        HOME, DOUBLE,
        tc(8, 894, 459, 304, '战士的试炼'),
        C('U', 'need', '181', '6'),
    ), env={'SHITU_QID': '181'}),
    Step('dew', 'late', (
        C('U', 'space', '3'),
        C('tower1_go.py'),
        C('dew_team.py', '{M}', '{APPS:0}'),
    ), env={'SHITU_QID': '181'}),
    Step('pour', 'late', (
        C('U', 'space', '4'),                   # 拿起馒头 hands out an item; 亿万56 (40/40) got no dialog 3 passes
        HOME, DOUBLE,
        C('guji_entrance.py'),
        C('go_goal.py', '650', '650', '2542', '3442'),
        C('team_npc.py', '650', '986', '2542', '3442', '花露|拿起馒头', '181', '{M}', '{APPS}', '--no-regroup'),
        HOME, DOUBLE,
        tc(8, 894, 459, 304, '战士的试炼'),
        C('pp_chain.py', '龙之都', '平静海岸2区'),
        tc(20, 3174, 1251, 631, '战士的试炼'),
        C('U', 'need', '181', '99'),
    ), env={'SHITU_QID': '181'}),
    Step('q183', 'late', (
        PP_HOME,
        C('yongzhe_take.py', '{APPS}'),
        C('pp_chain.py', '恶人山', '平静海岸2区', '龙之都'),
        C('desert_go.py'),
        tc(170, 1890, 567, 2202, '勇者'),
        C('scorpion_water.py', '{M}', '{APPS}'),
        HOME, DOUBLE, C('U', 'restock', '20'),
        C('pp_chain.py', '龙之都', '平静海岸2区'),
        tc(20, 3174, 1251, 631, '勇者'),
        tc(20, 4806, 309, 577, '勇者'),
        C('U', 'need', '183', '4'),
    ), env={'SHITU_QID': '183'}),
    Step('corpse', 'late', (
        C('U', 'space', '3'),
        C('pp_chain.py', '恶人山', '平静海岸2区', '龙之都'),
        C('ruin_go.py', '3030', '4569'),
        C('team_npc.py', '1000', '966', '3030', '4569', '勇者|安魂曲|拾取', '183', '{M}', '{APPS}', '--no-regroup'),
        HOME, DOUBLE,
        C('pp_chain.py', '龙之都', '平静海岸2区'),
        tc(20, 4806, 309, 577, '勇者'),
        C('U', 'need', '183', '6'),
    ), env={'SHITU_QID': '183'}),
    Step('king', 'late', (
        C('U', 'space', '3'),
        C('pp_chain.py', '恶人山', '平静海岸2区', '龙之都'),
        C('ruin_go.py', '2682', '3285'),
        C('scorpion_king.py', '{A0}', '{M}', '{REST}'),
        HOME, DOUBLE,
        C('sell_tradable.py', '--stones', '{APPS}'),
        C('pp_chain.py', '龙之都', '平静海岸2区'),
        tc(20, 4806, 309, 577, '勇者'),
        tc(20, 3174, 1251, 631, '勇者'),
        C('U', 'need', '183', '8'),
    ), env={'SHITU_QID': '183'}),
    # no DOUBLE before 神仙姐姐 / 出师 (user 2026-11-03): nothing is leveled after them, a 加钙地瓜 eaten there is wasted
    # (元素使 team 09:36: each ate one right before 出师)
    Step('fairy', 'late', (HOME, C('ops', 'fairy')), env={'SHITU_QID': '183'}),
    Step('chushi', 'late', (HOME, C('U', 'space', '2'), C('chushi.py', '{M}', '{APPS}'))),
    Step('finish', 'late', (
        C('open_packs.py', '{APPS}', soft=True),
        C('sell_tradable.py', '--safe', '{APPS}', soft=True),
        C('U', 'space', '6'),                   # 2026-10-28 亿万15: 39/40 bag, mail_sell took nothing
        C('mail_sell.py', '{APPS}', soft=True),
    )),
)

# ---- B+ (2026-10-30, user: one live batch with 伏地魔2): the v5 route minus the trips the levels don't need.
#   - no 'start' trip home at 23 (考验一二): 八阵图 goes straight on (B+ levels maze2 = bazhen = 23, bazhen is skipped);
#     考验一 + 二 + 三 are handed in together at the tower1 -> tower2 visit home (mm01 did all three at 31, ANALYSIS.md 2)
#   - 通天塔二区 stops at the team's tower2 'L+E' (default 'auto' = plan.tower2_auto): the 181 reward + the late quests' battles up to
#     蝎子王 count toward 40 (live: ~19.2万), only the 183 reward + 出师 come after it
#   - 181 (table level 35) / 183 (38) are taken at 38-39 (live 2026-10-30: both OK), but the 183 hand-in at 神仙姐姐
#     (转勇者) needs 40, so 'topup' patrols 二区 to 40 right before 'fairy' when the quests did not get there
#   - 飞鞋 (user 2026-10-30: once an hour, not recordable in mazes): recorded where the team walks past anyway, used the
#     next time over the same field: 遗忘洞穴 entrance (cave records, snake flies, ~30 min apart) and 遗址 entrance
#     (corpse records, king flies, ~2 h 20 after snake). A fly that can't happen (record / cooldown) walks as before.
CAVE_DOOR = ('141', '3410', '252')          # 无尽平原2区, 遗忘洞穴 entrance NPC 10166 (go_cave.py)
RUIN_DOOR = ('170', '3068', '192')          # 苦无沙漠1区, 遗址 entrance NPC 10176 (ruin_go.py)


def shoe(op, door, **kw):
    return C('shoe_point.py', op, *door, '{M}', '{APPS}', soft=True, **kw)


def _bplus():
    steps = {s.name: s for s in ROUTE}

    def before(name, script, *new):          # the step's cmds with `new` inserted before its first `script` cmd
        cmds = steps[name].cmds
        i = next(k for k, c in enumerate(cmds) if c.args[0] == script)
        return Step(name, steps[name].stage, cmds[:i] + new + cmds[i:], steps[name].retry, steps[name].unless,
                    steps[name].env)
    # 2026-11-01 (user): the team takes the 外城传送员 to 无尽2路口 instead of walking map 20 (team_tp.py): the
    # apprentices start for 740 while the master takes 224 at 大个王 next to it. A miss is soft: go_goal walks as before.
    cave = before('cave', 'go_cave.py', C('go_goal.py', '20', *CAVE_DOOR), shoe('record', CAVE_DOOR))
    cave = Step('cave', 'mid', tuple(x for c in cave.cmds for x in (
        (C('team_tp.py', 'send', '{APPS}', soft=True), c, C('team_tp.py', 'go', '{M}', '{APPS}', soft=True))
        if c.args == ('ops', 'take224_master') else (c,))), cave.retry, cave.unless, cave.env)
    snake = before('snake', 'go_cave.py', shoe('fly', CAVE_DOOR, when='master_on 20'),
                   C('pp_chain.py', '龙之都', '平静海岸2区', when='master_on 1'),   # a half fly scrolled everybody home
                   C('team_tp.py', 'go', '{M}', '{APPS}', when='master_on 20', soft=True))   # no fly: teleport
    corpse = before('corpse', 'ruin_go.py', C('desert_go.py', *RUIN_DOOR[1:]), shoe('record', RUIN_DOOR))
    # 2026-11-01 (user): the apprentices stay at 大个王 after taking 224, no 外城传送员 trip to 无尽2路口: snake flies
    # from anywhere, and a walk (record / cooldown) starts from the master at the PP鸡 landing anyway
    def stay(step):
        return Step(step.name, step.stage, tuple(Cmd(c.args + ('--stay',), c.when, c.soft) if c.args[0] == 'take224.py'
                                                 else c for c in step.cmds), step.retry, step.unless, step.env)
    q224 = stay(steps['q224'])
    # 2026-11-01 (user): after the 40 拳手 the team scrolls home and rides the PP鸡 to 龙之都 instead of walking 142 ->
    # 男爵 (back_longeer: round 3 measured 1.2-1.4 min with 4-5 battles); talk_chain walks everybody from the landing
    quan = steps['quan']
    quan = Step('quan', quan.stage, tuple(x for c in quan.cmds for x in (
        (HOME, C('pp_chain.py', '龙之都', '平静海岸2区')) if c.args == ('back_longeer.py',) else (c,))),
        quan.retry, quan.unless, quan.env)
    snake = stay(snake)
    king = steps['king'].cmds
    i = next(k for k, c in enumerate(king) if c.args[0] == 'pp_chain.py')
    king = Step('king', 'late', king[:i] + (shoe('fly', RUIN_DOOR), Cmd(king[i].args, when='master_off 170'))
                + king[i + 1:], steps['king'].retry, steps['king'].unless, steps['king'].env)
    end = Step('end', 'mid', (HOME, C('sell_tradable.py', '--safe', '{APPS}'), C('U', 'space', '4'),
                              C('trial_run.py', '--armor', '3', '--master', '{M}', '{APPS}'),
                              C('trial3_run.py', '--master', '{M}', '{APPS}')), retry='leave')
    tower2 = Step('tower2', 'mid', (HOME, DOUBLE, C('tower2_go.py'), C('tower2_patrol.py', '{T2}'),
                                    C('ops', 'exp_note', 'tower2', soft=True)),
                  retry='leave', unless='exp_ge {T2}')
    topup = Step('topup', 'late', (HOME, DOUBLE, C('tower2_go.py'), C('tower2_patrol.py', '40')),
                 retry='leave', unless='lv_ge 40')
    # 181 / 183 never taken below 40 before: whoever the NPC refuses at 38 makes the whole team patrol 二区 to 40 first
    def to40(qid):
        w = f'lacks {qid}'
        return (C('U', 'home', when=w), C('U', 'double', when=w), C('tower2_go.py', when=w),
                C('tower2_patrol.py', '40', when=w), C('U', 'home', when=w))
    q181 = steps['q181'].cmds
    i = next(k for k, c in enumerate(q181) if c.args[0] == 'talk_chain.py')
    q181 = Step('q181', 'late', q181[:i] + (Cmd(q181[i].args, soft=True),) + to40(181) + (
        C('pp_chain.py', '龙之都', '平静海岸2区', when='lacks 181'), C('back_longeer.py', when='lacks 181'),
        Cmd(q181[i].args, when='lacks 181')) + q181[i + 1:], env=steps['q181'].env)
    q183 = steps['q183'].cmds
    i = next(k for k, c in enumerate(q183) if c.args[0] == 'yongzhe_take.py')
    q183 = Step('q183', 'late', q183[:i] + (Cmd(q183[i].args, soft=True),) + to40(183) + (
        C('pp_chain.py', '龙之都', '平静海岸2区', when='lacks 183'),
        Cmd(q183[i].args, when='lacks 183')) + q183[i + 1:], env=steps['q183'].env)
    # what the late quests earned after 二区 (plan.tower2_auto, user 2026-10-31): before the step's closing gate
    king = Step('king', 'late', king.cmds[:-1] + (C('ops', 'exp_note', 'king', soft=True),) + king.cmds[-1:],
                king.retry, king.unless, king.env)
    # the master's bag over 24 x 7 batches (user 2026-10-31, master_bag.py): the kinds it holds at the first batch are
    # its own; new kinds (drops) are sold / dropped when 5 slots are left (after a step's trip home) and every batch end.
    # The batch ends with every apprentice's gold traded to the master.
    arm = Step('arm', 'make', steps['arm'].cmds + (C('master_bag.py', 'snapshot', '{M}', soft=True),), steps['arm'].retry)
    finish = Step('finish', 'late', steps['finish'].cmds + (
        C('give_gold.py', '{M}', '{APPS}'),
        C('U', 'home'),
        C('master_bag.py', 'clean', '{M}', soft=True)))
    out = []
    for s in ROUTE:
        if s.name == 'start':
            continue
        if s.name == 'fairy':        # 2026-10-30 live: 神仙姐姐「等你40级了再来找我吧…勇者就职礼」at 39
            out.append(topup)
        out.append({'end': end, 'tower2': tower2, 'q224': q224, 'quan': quan, 'q181': q181, 'q183': q183, 'cave': cave, 'snake': snake,
                    'corpse': corpse, 'king': king, 'arm': arm, 'finish': finish}.get(s.name, s))
    return tuple(_bag_check(x) for x in out)


BAG_CHECK = C('master_bag.py', 'clean', '{M}', '--if-free', '5', soft=True)


def _bag_check(s):
    """Right after a step's first trip home (逍遥村, next to the shop) the master's bag is cleaned when 5 slots are left."""
    if not s.cmds or s.cmds[0] != HOME:
        return s
    return Step(s.name, s.stage, s.cmds[:1] + (BAG_CHECK,) + s.cmds[1:], s.retry, s.unless, s.env)


ROUTE_BPLUS = _bplus()
ROUTES = {'v5': ROUTE, 'bplus': ROUTE_BPLUS}


# ---- 元素使 (user 2026-11-03: optional, a team with job = "术士"; the default stays 勇者 and ROUTE / ROUTE_BPLUS are
# not touched, tests/test_line.py pins them). Built on B+: 10 级 术士 (task 25, 水滴精灵 books instead of 拳手), a
# 35 级 白装 trip before 通天塔二区, and 187 术士的试炼 + 189 元素使的考验 instead of 181 + 183. Every step and NPC
# answer was recorded live with the first 元素使 batch (research/shitu/YUANSU_NOTES.md, 2026-11-02 / 03).
def tn(map_id, npc, x, y, words, qid):          # team_npc: every apprentice talks to the NPC at once
    return C('team_npc.py', *map(str, (map_id, npc, x, y)), words, str(qid), '{M}', '{APPS}', '--no-regroup')


DRAGON = C('pp_chain.py', '龙之都', '平静海岸2区')
TO_RUIN = (C('pp_chain.py', '恶人山', '平静海岸2区', '龙之都'), C('ruin_go.py', '4134', '3957'))
LADY = (20, 633, 3064, 1964)                    # 奥里雷西亚女士, 龙之都外城
LIU = (8, 305, 642, 351)                        # 半吊法师留一手, 逍遥村就职所
JACK = (20, 596, 3630, 2385)                    # 杰克·卡尔
YUANSU_LATE = (
    Step('y187', 'late', (HOME, C('U', 'restock', '20'), DRAGON,
                          tn(*LADY, '进行术士的试炼|接受任务', 187),
                          C('U', 'need', '187', '1')), env={'SHITU_QID': '187'}),
    # 留一手 -> 逍遥古迹 精灵巫师: 10 完美的魔法石 (stones.py) -> 清明长老 完美无暇的能量石 -> 留一手: 优秀术士证书
    Step('y_stone', 'late', (HOME, tn(*LIU, '术士的试炼', 187), C('U', 'space', '6'), C('stones.py'), DRAGON,
                             tn(20, 580, 2584, 1884, '术士的试炼|完美无暇', 187), HOME, tn(*LIU, '术士的试炼', 187),
                             C('U', 'need', '187', '4')), env={'SHITU_QID': '187'}),
    # 虫洞法师 -> 通天塔一区 5 色妖道 within 2 h (second 证书) -> 虫洞法师
    Step('y_yaodao', 'late', (HOME, C('pp_chain.py', '乌龙村', '平静海岸2区'),
                              tn(15, 203, 498, 249, '术士的试炼|来就来|走着', 187), HOME, C('yaodao.py'),
                              C('pp_chain.py', '乌龙村', '平静海岸2区'), tn(15, 203, 498, 249, '术士的试炼', 187),
                              C('U', 'need', '187', '6')), env={'SHITU_QID': '187'}),
    # 奥里雷西亚 -> 苦无沙漠1区 猥琐教打杂的 10 神仙姐姐的画像 -> 奥里雷西亚 (the teleport offer is declined here)
    Step('y_huaxiang', 'late', (HOME, DRAGON, tn(*LADY, '术士的试炼|说吧|太可恶|明白', 187), C('U', 'space', '6'),
                                C('farm.py', '170', '1062', '1221', '10716', '10', 'desert_go.py', '1062', '1221'),
                                DRAGON, tn(*LADY, '术士的试炼|哦，啊|好的|考虑', 187),
                                C('U', 'need', '187', '8')), env={'SHITU_QID': '187'}),
    # 死鸟人: one-by-one teleports + the master walks in, a 女神奖杯 each -> 奥里雷西亚: 187 done (奖学金)
    Step('y_bird', 'late', (HOME, DRAGON, C('bird.py', '{M}', '{APPS}'), HOME, DRAGON,
                            tn(*LADY, '术士的试炼|亮出|会的', 187), C('U', 'need', '187', '99')),
         env={'SHITU_QID': '187'}),
    Step('y189', 'late', (HOME, DRAGON, tn(*LADY, '进行术士转职考验|成为元素使|接受任务', 189),
                          C('U', 'need', '189', '7')), env={'SHITU_QID': '189'}),
    Step('y_fire', 'late', (HOME, DRAGON, C('fire.py', '{M}', '{APPS}'), C('U', 'have', '10722', '1')),
         env={'SHITU_QID': '189'}),
    # 水侯爷 兰花束 -> 余美人 -> 水侯爷: 5 水之精华
    Step('y_water', 'late', (HOME, DRAGON, C('go_goal.py', '20', '150', '1494', '900', '140', '141', '142'),
                             tn(150, 1701, 1494, 855, '元素使|怎么了|找个回来|好美|给我花', 189),
                             C('go_goal.py', '150', '150', '1890', '2550'),
                             tn(150, 1702, 1890, 2511, '元素使|水侯爷给你的花|再见', 189),
                             C('go_goal.py', '150', '150', '1494', '900'),
                             tn(150, 1701, 1494, 855, '元素使|没有|谢谢了', 189),
                             C('U', 'have', '10720', '5')), env={'SHITU_QID': '189'}),
    # 风娃娃 first, then 杰克·卡尔: only after both do 猴娃娃 / 嫩竹爱好者 drop the 毛皮 / 细绒毛 (79 battles for nothing)
    Step('y_wind1', 'late', (HOME, *TO_RUIN, tn(1000, 1132, 4134, 3957, '元素使|龙之都吧|风之气息|好吧', 189),
                             HOME, DRAGON, tn(*JACK, '元素使|只要会说话|怎么找|知道了', 189)), env={'SHITU_QID': '189'}),
    # 迷惑森林1区: 5 毛皮 + 5 细绒毛, then 秘密宝窟 土拨鼠 (mole.py: activate each, fight per leader that lacks)
    Step('y_doll', 'late', (HOME, DRAGON, C('go_goal.py', '20', '150', '3822', '1527', '140', '141', '142'),
                            C('farm.py', '--stay', '150', '3822', '1527', '10728', '5'),
                            C('farm.py', '--stay', '150', '3700', '2181', '10729', '5'),
                            C('mole.py', '{M}', '{APPS}'), C('U', 'have', '10721', '1')), env={'SHITU_QID': '189'}),
    # 杰克·卡尔 机器娃娃 -> 风娃娃 风之气息
    Step('y_wind2', 'late', (HOME, DRAGON, tn(*JACK, '元素使|谢谢', 189), C('U', 'have', '10730', '1'),
                             HOME, *TO_RUIN, tn(1000, 1132, 4134, 3957, '元素使|给你', 189),
                             C('U', 'have', '10719', '1')), env={'SHITU_QID': '189'}),
    # 通天塔3号房 第五元素 (rooms.py, then fifth.py one by one as leader) -> 奥里雷西亚
    Step('y_fifth', 'late', (HOME, C('rooms.py', '{A0}', '{M}', '{APPS}'), C('fifth.py', '{APPS}'),
                             C('U', 'have', '10732', '1'), HOME, DRAGON, tn(*LADY, '元素使的考验|给你吧', 189),
                             C('U', 'need', '189', '9')), env={'SHITU_QID': '189'}),
)
GEAR = Step('gear', 'mid', (HOME, DRAGON, C('buy_gear.py', '{APPS}')), retry='leave')   # 乐乐姐 35 级 恶魔白装
BRAVE = ('q181', 'quan', 'wulong', 'tree', 'crystal', 'dew', 'pour', 'q183', 'corpse', 'king')


def _yuansu():
    out = []
    for s in ROUTE_BPLUS:
        if s.name == 'zhuanzhi':             # task 25: 水滴精灵 books (shuidi.py) instead of the 拳手 (quanshou.py)
            s = Step(s.name, s.stage, tuple(C('shuidi.py') if c.args[0] == 'quanshou.py' else c for c in s.cmds),
                     s.retry, s.unless, s.env)
        elif s.name == 'tower2':
            out.append(GEAR)
        elif s.name == 'q181':
            out.extend(YUANSU_LATE)
        elif s.name == 'fairy':
            s = Step(s.name, s.stage, s.cmds, s.retry, s.unless, {'SHITU_QID': '189'})
        if s.name in BRAVE:
            continue
        out.append(s)
    return tuple(_bag_check(x) for x in out)


ROUTE_YUANSU = _yuansu()


def _yongzhe(steps):
    """The 勇者 lines (v5, B+; not the 元素使 one, built above from the B+ steps as they were): the apprentices own no
    weapon (user 2026-11-04: bare hands = a shorter 蓄力; well10.Unarm takes the 专打屁屁扳手 off at 2). Every sale
    takes the worn weapon off and sells all weapons (sell_tradable --weapons, never a master's), wear_best puts on
    no weapon (--no-weapon)."""
    add = {'sell_tradable.py': '--weapons', 'wear_best.py': '--no-weapon'}

    def cmd(c):
        flag = add.get(c.args[0])
        return Cmd(c.args + (flag,), c.when, c.soft) if flag and flag not in c.args else c
    return tuple(Step(s.name, s.stage, tuple(cmd(c) for c in s.cmds), s.retry, s.unless, s.env) for s in steps)


ROUTE, ROUTE_BPLUS = _yongzhe(ROUTE), _yongzhe(ROUTE_BPLUS)
ROUTES = {'v5': ROUTE, 'bplus': ROUTE_BPLUS}


def route_of(b):
    """The steps a batch runs (its team's line.toml route; B+ unless the team says route = "v5"). A team with
    job = "术士" runs the 元素使 line (B+ based); every other team runs exactly what it ran before."""
    if getattr(b, 'job', '战士') == '术士':
        return ROUTE_YUANSU
    return ROUTES[getattr(b, 'route', 'bplus')]


NAMES = [s.name for s in ROUTE]


def step(name):
    return ROUTE[NAMES.index(name)]


def fill(text, b):
    """{T1} / {LV:key} in a token or a when / unless condition -> the batch's numbers."""
    text = text.replace('{T1}', str(b.tower1))
    if '{T2}' in text:
        text = text.replace('{T2}', getattr(b, 'tower2', '40'))
    return re.sub(r'\{LV:(\w+)\}', lambda m: str(b.level(m.group(1))), text)


def expand(cmd, b, python=('python', '-X', 'utf8')):
    """Cmd + plan.Batch -> list of argv lists (one per apprentice for a par Cmd)."""
    apps = b.apprentices
    head = list(python) + (['r4_util.py'] if cmd.args[0] == 'U' else ['-m', 'line.ops'] if cmd.args[0] == 'ops'
                           else [cmd.args[0]])

    def one(a=None):
        out = list(head)
        for tok in cmd.args[1:]:
            out += {'{M}': [b.master], '{APPS}': apps, '{A0}': apps[:1], '{REST}': apps[1:], '{A}': [a],
                    '{APPS:0}': [f'{n}:0' for n in apps], '{PAIRS}': b.pairs, '{PREV}': b.prev_names,
                    '{T1}': [str(b.tower1)], '{T2}': [getattr(b, 'tower2', '40')]}.get(tok, [fill(tok, b)])
        return out
    return [one(a) for a in apps] if cmd.par else [one()]
