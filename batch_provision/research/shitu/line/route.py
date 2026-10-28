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
Cmd.when = ops condition ('lv_lt 25', 'master_on 1', 'kills5'): the Cmd only runs when it holds.
Step.unless = ops condition: the whole step is skipped when it holds (leveling already done).

Lessons from rounds 1-4 that are rules here (tests/test_line.py checks them):
  - a step that ends by going home never regroups first (team_npc --no-regroup; user 2026-10-28)
  - every late quest step ends with a gate `U need QID N` (a lagging apprentice is caught at the step it fell behind)
  - nothing runs from logs/ (gitignored: round 4's cave step ran logs/gather_all.sh, absent from a fresh clone)
  - before steps that pick up quest items the bag gets free slots (U space; a full bag loses them silently)
"""
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
    Step('pp', 'early', (C('supply_go.py'), C('pp_unlock.py', '{APPS}')), retry='leave'),
    Step('lunhui', 'early', (C('lunhui15.py'),), retry='leave', unless='lv_ge 15'),
    Step('maze', 'early', (C('maze_train.py'),), retry='leave'),

    # ---- mid: 考验一二 -> 八阵图 25 -> 遗忘洞穴 25->28 (+采集) -> 224 -> 地头蛇 -> 通天一 28->33 -> 考验三 -> 二区 ->40
    Step('start', 'mid', (HOME, C('sell_tradable.py', '--safe', '{APPS}'),
                          C('trial_run.py', '--armor', '3', '--master', '{M}', '{APPS}')), retry='leave'),
    Step('bazhen', 'mid', (HOME, C('pp_chain.py', '平静海岸2区'), C('bazhen25.py', '25')),
         retry='leave', unless='lv_ge 25'),
    Step('cave', 'mid', (
        HOME, C('pp_chain.py', '龙之都', '平静海岸2区'), C('U', 'leave'),
        C('ops', 'take224_master'),
        C('go_cave.py'),
        C('ops', 'gather'),                                  # the master: 9 花 + 3 遗忘之石 (was logs/gather_all.sh)
        C('cave_train.py', '28', when='lv_lt 28'),
    ), retry='leave'),
    Step('q224', 'mid', (HOME, C('pp_chain.py', '龙之都', '平静海岸2区'), C('U', 'leave'),
                         C('take224.py', '{A}')), retry='leave'),
    Step('snake', 'mid', (C('go_cave.py'), C('dts.py')), retry='leave'),
    Step('tower1', 'mid', (HOME, DOUBLE, C('pp_chain.py', '通天塔', '平静海岸2区'), C('tower28.py', '33')),
         retry='leave', unless='lv_ge 33'),
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
    Step('fairy', 'late', (HOME, DOUBLE, C('ops', 'fairy')), env={'SHITU_QID': '183'}),
    Step('chushi', 'late', (HOME, DOUBLE, C('U', 'space', '2'), C('chushi.py', '{M}', '{APPS}'))),
    Step('finish', 'late', (
        C('open_packs.py', '{APPS}', soft=True),
        C('sell_tradable.py', '--safe', '{APPS}', soft=True),
        C('U', 'space', '6'),                   # 2026-10-28 亿万15: 39/40 bag, mail_sell took nothing
        C('mail_sell.py', '{APPS}', soft=True),
    )),
)

NAMES = [s.name for s in ROUTE]


def step(name):
    return ROUTE[NAMES.index(name)]


def expand(cmd, b, python=('python', '-X', 'utf8')):
    """Cmd + plan.Batch -> list of argv lists (one per apprentice for a par Cmd)."""
    apps = b.apprentices
    head = list(python) + (['r4_util.py'] if cmd.args[0] == 'U' else ['-m', 'line.ops'] if cmd.args[0] == 'ops'
                           else [cmd.args[0]])

    def one(a=None):
        out = list(head)
        for tok in cmd.args[1:]:
            out += {'{M}': [b.master], '{APPS}': apps, '{A0}': apps[:1], '{REST}': apps[1:], '{A}': [a],
                    '{APPS:0}': [f'{n}:0' for n in apps], '{PAIRS}': b.pairs, '{PREV}': b.prev_names}.get(tok, [tok])
        return out
    return [one(a) for a in apps] if cmd.par else [one()]
